"""Small synchronous PDF-only deployment API. No job queue or retained documents."""
import asyncio
from contextlib import asynccontextmanager
import gc
import logging
from pathlib import Path
import tempfile
import threading
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from module.cancellation import ProcessingCancelled, cancellation_scope
from .schemas import VBHCPredictionResponse
from .security import load_api_key, require_api_key

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024


class UploadRejected(Exception):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail


class PdfAdmission:
    """Acquire before multipart parsing; never buffer a second upload in the app."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/ocr/pdf" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        request = Request(scope)
        state = scope["app"].state
        from fastapi.security import HTTPAuthorizationCredentials
        header = request.headers.get("authorization", "").split()
        credentials = (HTTPAuthorizationCredentials(scheme=header[0], credentials=header[1])
                       if len(header) == 2 and header[0].lower() == "bearer" else None)
        try:
            await require_api_key(request, credentials)
        except HTTPException as error:
            return await JSONResponse({"detail": error.detail}, status_code=error.status_code,
                                      headers=error.headers)(scope, receive, send)
        if not state.ready or state.busy:
            return await JSONResponse({"detail": "OCR busy or not ready"}, status_code=503,
                                      headers={"Retry-After": "10"})(scope, receive, send)
        # No await between testing and setting: atomic within the single event loop.
        state.busy = True
        count = 0
        started = False
        upload_deadline = time.monotonic() + 300

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        async def limited_receive():
            nonlocal count
            try:
                remaining = upload_deadline - time.monotonic()
                if remaining <= 0:
                    raise UploadRejected(408, "Upload total timeout")
                message = await asyncio.wait_for(receive(), timeout=min(60, remaining))
            except TimeoutError:
                raise UploadRejected(408, "Upload idle timeout") from None
            if message["type"] == "http.request":
                count += len(message.get("body", b""))
                if count > MAX_BODY_BYTES:
                    raise UploadRejected(413, "Upload exceeds 100 MiB plus multipart overhead")
            return message

        try:
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    size = int(length)
                except ValueError:
                    raise UploadRejected(400, "Invalid Content-Length") from None
                if size < 0 or size > MAX_BODY_BYTES:
                    raise UploadRejected(413, "Upload exceeds limit")
            await self.app(scope, limited_receive, tracked_send)
        except UploadRejected as error:
            if not started:
                await JSONResponse({"detail": error.detail}, status_code=error.status)(scope, receive, send)
            else:
                raise
        finally:
            state.busy = False


def build_uat_pipeline():
    # Heavy imports only at startup; tests can inject a tiny pipeline factory.
    import torch
    from ruamel.yaml import YAML
    from module.pipeline import build_pipeline
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    config_path = Path(__file__).resolve().parents[1] / "conf/uat.yaml"
    conf = YAML(typ="safe").load(config_path.read_text())
    return build_pipeline(conf)


def release_request_memory():
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


async def run_inference(request, path, filename, event):
    def work():
        with cancellation_scope(event):
            return request.app.state.pipeline.process_pdf(str(path), source_filename=filename)

    task = asyncio.create_task(asyncio.to_thread(work))
    deadline = time.monotonic() + 3600
    try:
        while not task.done():
            if await request.is_disconnected():
                event.set()
            if time.monotonic() > deadline:
                event.set()
            await asyncio.wait({task}, timeout=0.25)
        result = task.result()
        if event.is_set():
            raise ProcessingCancelled("Client disconnected or processing timeout")
        return result
    finally:
        # Cancelling an await does not stop a native inference call. Keep the slot
        # and input file until the thread reaches a cancellation checkpoint.
        if not task.done():
            event.set()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if task.done() and not task.cancelled():
            task.exception()  # retrieve errors even if the request task was cancelled


def create_app(pipeline_factory=build_uat_pipeline):
    @asynccontextmanager
    async def lifespan(app):
        app.state.api_key = load_api_key()
        if app.state.api_key == "REPLACE_WITH_RANDOM_TOKEN":
            raise RuntimeError("Replace the example VOCR_API_KEY before deployment")
        app.state.ready = False
        app.state.busy = False
        app.state.pipeline = await asyncio.to_thread(pipeline_factory)
        app.state.ready = True
        yield
        app.state.ready = False
        app.state.pipeline = None

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ready = False
    app.state.busy = False
    app.add_middleware(PdfAdmission)

    @app.get("/health")
    async def health(request: Request):
        ready = request.app.state.ready
        return JSONResponse({"status": "ready" if ready else "not_ready", "model_loaded": ready,
                             "busy": request.app.state.busy}, status_code=200 if ready else 503)

    @app.post("/api/v1/ocr/pdf", response_model=VBHCPredictionResponse,
              response_model_exclude_none=True, dependencies=[Depends(require_api_key)])
    async def pdf(request: Request):
        try:
            # Parse inside the admitted slot. Spooled files are closed on every exit.
            async with request.form(max_files=1, max_fields=0, max_part_size=64 * 1024) as form:
                file = form.get("file")
                if not isinstance(file, UploadFile):
                    raise HTTPException(422, "Multipart file field 'file' is required")
                filename = Path((file.filename or "").replace("\\", "/")).name
                if not filename.lower().endswith(".pdf"):
                    raise HTTPException(400, "Only .pdf files are supported")
                with tempfile.TemporaryDirectory(prefix="ocr-request-") as directory:
                    path = Path(directory) / "input.pdf"
                    size = 0
                    with path.open("wb") as output:
                        while chunk := await file.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_FILE_BYTES:
                                raise HTTPException(413, "PDF exceeds 100 MiB")
                            output.write(chunk)
                    if not size:
                        raise HTTPException(400, "Uploaded file is empty")
                    event = threading.Event()
                    try:
                        return await run_inference(request, path, filename, event)
                    finally:
                        release_request_memory()
        except ProcessingCancelled:
            raise HTTPException(408, "Processing cancelled") from None
        except ClientDisconnect:
            raise HTTPException(400, "Client disconnected during upload") from None
        except (StarletteHTTPException, UploadRejected):
            raise
        except Exception as error:
            from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError, PDFPopplerTimeoutError
            if isinstance(error, (PDFPageCountError, PDFSyntaxError)):
                raise HTTPException(422, "Invalid, encrypted or unreadable PDF") from None
            if isinstance(error, PDFPopplerTimeoutError):
                raise HTTPException(408, "PDF rendering timed out") from None
            logger.exception("PDF processing failed")
            raise HTTPException(500, "Internal processing error") from None

    return app


app = create_app()

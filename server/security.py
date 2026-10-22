"""HTTP security without importing OCR models or exposing server secrets to the UI."""

import ipaddress
import os
import secrets
from pathlib import Path
from typing import Annotated, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from .schemas import VBHCPredictionResponse

_bearer = HTTPBearer(auto_error=False)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def load_api_key() -> str:
    """Fail before model loading; dotenv loading belongs to the server launcher."""
    key = os.environ.get("VOCR_API_KEY", "")
    if not key or not key.isascii() or not key.isprintable() or any(c.isspace() for c in key):
        raise RuntimeError("VOCR_API_KEY must be a nonempty ASCII token without whitespace")
    return key


async def require_api_key(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    key = getattr(request.app.state, "api_key", None)
    if not key:
        raise HTTPException(status_code=503, detail="API authentication is not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), key.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid origin")
    port = parsed.port
    if port is None:
        port = {"http": 80, "https": 443}.get(parsed.scheme)
    return parsed.scheme, parsed.hostname, port


async def require_local_debug(request: Request) -> None:
    """Defense in depth, not a substitute for a loopback-only listening socket.

    Do not put this debug service behind any reverse proxy or tunnel. A proxy
    that hides its forwarding headers cannot be distinguished from a local client.
    """
    try:
        loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        local_host = request.url.hostname in _LOCAL_HOSTS
        origin = request.headers.get("origin")
        same_origin = origin is None or _origin(origin) == _origin(str(request.url))
    except ValueError:
        loopback = local_host = same_origin = False
    forwarded = any(
        name in {"forwarded", "via", "x-real-ip"} or name.startswith("x-forwarded-")
        for name in request.headers
    )
    if (
        not loopback
        or not local_host
        or not same_origin
        or forwarded
        or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
    ):
        raise HTTPException(status_code=403, detail="Local debug access only")


class _LocalDebugFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        try:
            await require_local_debug(Request(scope))
        except HTTPException as exc:
            response = JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code,
                headers={"Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return

        async def send_no_store(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value) for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        await super().__call__(scope, receive, send_no_store)


def configure_http_routes(
    app: FastAPI,
    router: APIRouter,
    pdf_endpoint: Callable,
    *,
    debug_enabled: bool,
    output_dir: str | Path,
    static_dir: str | Path,
) -> None:
    """Always authenticate public APIs; register local surfaces only on opt-in."""
    app.include_router(router, dependencies=[Depends(require_api_key)])
    if not debug_enabled:
        return

    async def debug_access(request: Request, response: Response) -> None:
        await require_local_debug(request)
        response.headers["Cache-Control"] = "no-store"

    debug_router = APIRouter(dependencies=[Depends(debug_access)], include_in_schema=False)
    debug_router.add_api_route(
        "/debug/ocr/pdf", pdf_endpoint, methods=["POST"],
        response_model=VBHCPredictionResponse, response_model_exclude_none=True,
    )
    app.include_router(debug_router)
    # The output mount must precede the catch-all UI mount.
    app.mount("/pipeline_outputs", _LocalDebugFiles(directory=output_dir), name="pipeline_outputs")
    app.mount("/", _LocalDebugFiles(directory=static_dir, html=True), name="static")

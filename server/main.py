import logging

# Must run before any other import (paddle/paddlex configure the root
# logger as a side effect of import, which makes basicConfig() a silent
# no-op if it runs after them -- our own INFO logs would then vanish while
# uvicorn's independently-configured access logs still show up fine).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import os  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from module.extract import ExtractBackend, get_extract_backend  # noqa: E402
from module.pipeline import DocumentPipeline, PipelineConfig, build_pipeline, load_pipeline_conf  # noqa: E402

from . import routes  # noqa: E402
from .deps import get_extractor, get_pipeline  # noqa: E402

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Loaded once here (cheap -- just YAML, no models) so output_dir is known
# for the /pipeline_outputs mount below WITHOUT waiting on build_pipeline()
# in lifespan (which loads every model and only runs once uvicorn starts
# serving). The SAME dict is then handed to build_pipeline() in lifespan so
# the config file isn't parsed twice.
_conf = load_pipeline_conf()
_output_dir = PipelineConfig.from_conf(_conf).output_dir
os.makedirs(_output_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading OCR pipeline (layout/OCR/TSR models)...")
    app.state.pipeline = build_pipeline(_conf)
    logger.info("Pipeline ready")
    logger.info("Loading entity-extraction model...")
    app.state.extractor = get_extract_backend(_conf)
    logger.info("Extractor ready")
    yield
    app.state.pipeline = None
    app.state.extractor = None


app = FastAPI(title="DeepDoc FastOCR API", lifespan=lifespan)


@app.get("/health")
async def health(
    pipeline: DocumentPipeline = Depends(get_pipeline),
    extractor: ExtractBackend = Depends(get_extractor),
) -> dict:
    """Liveness/readiness check -- 200 once BOTH the OCR pipeline and the
    entity-extraction model have finished loading (via the same
    get_pipeline/get_extractor dependencies the real routes use), 503 while
    either is still starting up or failed to load."""
    return {"status": "ok"}


app.include_router(routes.router)
# Serves DocumentPipeline.process_pdf()'s saved per-page preview images (see
# its "page_image" URLs in the JSON response) -- MUST be mounted before the
# catch-all "/" mount below: Starlette matches mounts in registration order,
# so a mount added AFTER "/" would never be reached (every path starts with
# "/", so that catch-all would already have claimed it first).
app.mount("/pipeline_outputs", StaticFiles(directory=_output_dir), name="pipeline_outputs")
# Mounted last so it doesn't shadow the routes above -- serves
# server/static/index.html at "/" as a minimal manual-test UI for the API.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

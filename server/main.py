import logging

# Must run before any other import (paddle/paddlex configure the root
# logger as a side effect of import, which makes basicConfig() a silent
# no-op if it runs after them -- our own INFO logs would then vanish while
# uvicorn's independently-configured access logs still show up fine).
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import os  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from module.extract import get_extract_backend  # noqa: E402
from module.pipeline import PipelineConfig, build_pipeline, load_pipeline_conf  # noqa: E402

from . import routes  # noqa: E402
from .security import configure_http_routes, load_api_key  # noqa: E402

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Loaded once here (cheap -- just YAML, no models) so output_dir is known
# for the /pipeline_outputs mount below WITHOUT waiting on build_pipeline()
# in lifespan (which loads every model and only runs once uvicorn starts
# serving). The SAME dict is then handed to build_pipeline() in lifespan so
# the config file isn't parsed twice.
_conf = load_pipeline_conf()
_pipeline_config = PipelineConfig.from_conf(_conf)
_output_dir = _pipeline_config.output_dir
os.makedirs(_output_dir, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.api_key = load_api_key()
    logger.info("Loading OCR pipeline (layout/OCR/TSR models)...")
    app.state.pipeline = build_pipeline(_conf)
    logger.info("Pipeline ready")
    app.state.extract_enabled = _conf.get("extract", {}).get("enabled", True)
    if app.state.extract_enabled:
        logger.info("Loading entity-extraction model...")
        app.state.extractor = get_extract_backend(_conf)
        logger.info("Extractor ready")
    else:
        logger.info("Entity extraction disabled by configuration")
        app.state.extractor = None
    yield
    app.state.pipeline = None
    app.state.extractor = None


app = FastAPI(
    title="DeepDoc FastOCR API", lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
configure_http_routes(
    app, routes.router, routes.ocr_pdf,
    debug_enabled=_pipeline_config.debug_enabled,
    output_dir=_output_dir, static_dir=STATIC_DIR,
)

from fastapi import HTTPException, Request

from module.extract import ExtractBackend
from module.pipeline import DocumentPipeline


def get_pipeline(request: Request) -> DocumentPipeline:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline is not ready")
    return pipeline


def get_extractor(request: Request) -> ExtractBackend:
    extractor = getattr(request.app.state, "extractor", None)
    if extractor is None:
        raise HTTPException(status_code=503, detail="Extractor is not ready")
    return extractor

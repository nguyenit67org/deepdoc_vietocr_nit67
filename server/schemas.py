from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OCRResponse(BaseModel):
    file: str
    json_data: dict = Field(alias="json")
    markdown: str

    model_config = ConfigDict(populate_by_name=True)


class PredictionField(BaseModel):
    value: str
    type: Literal["string"]

    model_config = ConfigDict(extra="forbid")


class PredictionDateField(PredictionField):
    value: str = Field(pattern=r"^(?:$|(0[1-9]|[12][0-9]|3[01])/(0[1-9]|1[0-2])/\d{4})$")


class PredictionPriorityField(PredictionField):
    value: Literal[
        "0_BÌNH THƯỜNG",
        "1_HỎA TỐC",
        "2_KHẨN",
        "3_THƯỢNG KHẨN",
    ]


class PredictionSecurityField(PredictionField):
    value: Literal[
        "0_BÌNH THƯỜNG",
        "1_MẬT",
        "2_TỐI MẬT",
        "3_TUYỆT MẬT",
    ]


class VBHCInformation(BaseModel):
    type: PredictionField
    title: PredictionField
    code: PredictionField
    documentDate: PredictionDateField
    officeSender: PredictionField
    recipients: PredictionField
    signer: PredictionField
    priority_level: PredictionPriorityField
    security_level: PredictionSecurityField
    first_recipients: PredictionField
    signer_title: PredictionField
    province: PredictionField
    receiverDate: PredictionDateField

    model_config = ConfigDict(extra="forbid")


class DebugLayoutBlock(BaseModel):
    id: int
    type: str
    score: float | None = None
    bbox: list[float]


class DebugOCRLine(BaseModel):
    id: int
    text: str
    bbox: list[float]
    quad: list[list[float]]
    block_id: int | None = None


class DebugPageBlock(BaseModel):
    id: int
    type: str
    score: float
    content_type: str
    content: str | None = None
    bbox: list[float]
    source_layout_id: int | None = None
    ocr_line_ids: list[int]


class DebugExtractionEvidence(BaseModel):
    page: int
    block_id: int
    block_type: str
    source_layout_id: int | None = None
    rule: str
    value: str
    source_text: str
    bbox: list[float]
    bbox_normalized: list[float]
    geometry_reliable: bool


class DebugExtractionField(BaseModel):
    value: str
    status: Literal["matched", "default", "not_found"]
    evidence: list[DebugExtractionEvidence]


class DebugExtraction(BaseModel):
    document_start_page: int | None = None
    document_end_page: int | None = None
    next_document_start_page: int | None = None
    geometry_reliable: bool
    fields: dict[str, DebugExtractionField]


class DebugPage(BaseModel):
    page: int
    width: int
    height: int
    image_url: str
    layout_blocks: list[DebugLayoutBlock]
    ocr_lines: list[DebugOCRLine]
    blocks: list[DebugPageBlock]


class PipelineDebugResponse(BaseModel):
    version: Literal[1, 2]
    document_id: str | None = None
    source_filename: str | None = None
    pdf_path: str | None = None
    markdown: str
    pages: list[DebugPage]
    extraction: DebugExtraction

    @model_validator(mode="after")
    def require_v2_identity(self):
        if self.version == 2 and not all((self.document_id, self.source_filename, self.pdf_path)):
            raise ValueError("Trace v2 requires document_id, source_filename and pdf_path")
        return self


class VBHCPredictionResponse(BaseModel):
    information: list[VBHCInformation] = Field(min_length=1, max_length=1)
    processing_time: float = Field(ge=0)
    debug: PipelineDebugResponse | None = None

    model_config = ConfigDict(extra="forbid")


class ErrorResponse(BaseModel):
    detail: str


class BatchItemResult(BaseModel):
    """One file's outcome within a /pdfs or /images batch request. json/
    markdown are also written to output_dir on disk regardless (see
    DocumentPipeline.process_pdf_group/process_image_group), but are
    included here too so callers don't have to read them back off disk."""

    file: str
    status: str  # "success" | "error"
    output_dir: str | None = None
    json_data: dict | None = Field(default=None, alias="json")
    markdown: str | None = None
    error: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class BatchOCRResponse(BaseModel):
    results: list[BatchItemResult]


class ExtractRequest(BaseModel):
    text: str
    # {field_name: field_description} -- omit/empty to use the server's
    # default schema (conf/pipeline_conf.yaml's extract.schema, see
    # module/extract/get_default_schema()).
    schema_: dict[str, str] | None = Field(default=None, alias="schema")

    model_config = ConfigDict(populate_by_name=True)


class ExtractResponse(BaseModel):
    entities: dict[str, list[str]]


class SchemaField(BaseModel):
    key: str
    desc: str


class ExtractSchemaResponse(BaseModel):
    schema_: list[SchemaField] = Field(alias="schema")

    model_config = ConfigDict(populate_by_name=True)

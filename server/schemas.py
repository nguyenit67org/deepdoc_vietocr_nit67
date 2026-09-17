from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class VBHCPredictionResponse(BaseModel):
    information: list[VBHCInformation] = Field(min_length=1, max_length=1)
    processing_time: float = Field(ge=0)

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

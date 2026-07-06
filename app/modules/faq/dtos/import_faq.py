from typing import List, Optional
from pydantic import Field
from app.core.base_schema import BaseSchema
from app.modules.metadata.dtos.metadata_out import FaqMetadataResponse

class FaqImportRow(BaseSchema):
    row_index: int
    question: str
    answer_rich_text: str
    answer_markdown: str
    metadata: FaqMetadataResponse
    is_valid: bool
    error: Optional[str] = None

class FaqImportPreviewResponse(BaseSchema):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    rows: List[FaqImportRow]

class FaqImportExcelRequest(BaseSchema):
    question_col: str
    answer_col: str
    metadata_filter_json: str
    sheet_name: Optional[str] = None
    skip_rows: int = 1
    skip_duplicates: bool = True
    lecturer_only: bool = False  # áp cho toàn bộ batch import

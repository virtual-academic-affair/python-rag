from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

class SourceCitation(BaseSchema):
    citation_id: int = Field(..., description="ID of citation [1], [2], etc.")
    file_name: Optional[str] = Field(None, description="Document title/name")
    title: Optional[str] = Field(None, description="TOC Node title")
    file_id: Optional[str] = Field(None, description="File ID in database")
    pages: Optional[List[str]] = Field(None, description="Line ranges read by agent (e.g. ['10-50', '80-100'])")
    original_url: Optional[str] = Field(None, description="R2 URL to view the original document")
    markdown_url: Optional[str] = Field(None, description="R2 URL to view the markdown document")

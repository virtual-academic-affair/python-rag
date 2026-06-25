from typing import Optional
from pydantic import Field
from app.core.base_document import BaseDocument

class FormDocument(BaseDocument):
    documentType: str = Field(..., alias="documentType")
    contentLink: str = Field(..., alias="contentLink")
    notes: Optional[str] = None

    class Settings:
        name = "forms"
        use_state_management = True

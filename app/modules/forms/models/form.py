from typing import Optional
from datetime import datetime, timezone
from pydantic import Field
from app.core.base_document import BaseDocument

class FormDocument(BaseDocument):
    documentType: str = Field(..., alias="documentType")
    contentLink: str = Field(..., alias="contentLink")
    notes: Optional[str] = None

    # Override created_at/updated_at to map to camelCase MongoDB fields
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="createdAt"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        alias="updatedAt"
    )

    class Settings:
        name = "forms"
        use_state_management = True

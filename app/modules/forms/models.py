from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

class FormDocument(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    documentType: str
    contentLink: str
    notes: Optional[str] = None
    createdAt: datetime
    updatedAt: datetime
    
    class Config:
        populate_by_name = True

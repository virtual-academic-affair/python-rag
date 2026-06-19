from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

class UploadStep(Enum):
    """Steps in the upload process for tracking rollback."""
    VALIDATED = "validated"
    DB_CREATED = "db_created"
    R2_UPLOADED = "r2_uploaded"
    METADATA_SYNCED = "metadata_synced"
    COMPLETED = "completed"

@dataclass
class UploadState:
    """Track upload progress for intelligent rollback."""
    file_id: Optional[str] = None
    storage_path: Optional[str] = None
    table_of_contents: list[str] = field(default_factory=list)
    custom_metadata: Optional[dict] = None
    completed_steps: list = field(default_factory=list)

    def mark_step(self, step: UploadStep):
        self.completed_steps.append(step)
    
    def has_step(self, step: UploadStep) -> bool:
        return step in self.completed_steps

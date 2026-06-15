from beanie import Document, before_event, Replace, Update, SaveChanges
from datetime import datetime, timezone
from pydantic import Field

class BaseDocument(Document):
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @before_event([Replace, Update, SaveChanges])
    def touch_updated_at(self):
        self.updated_at = datetime.now(timezone.utc)

    class Settings:
        use_state_management = True

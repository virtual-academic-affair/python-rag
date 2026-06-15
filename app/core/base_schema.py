"""
Base Schemas — Global Pydantic configuration for naming conventions.
Enforces camelCase in JSON (responses) while accepting both snake_case and camelCase in requests.
"""
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    """Base schema for all API requests and responses.
    
    Attributes:
        alias_generator: Converts snake_case field names to camelCase for JSON.
        populate_by_name: Allows input to use either field name or alias.
        serialize_by_alias: Ensures JSON output uses camelCase aliases.
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
    )

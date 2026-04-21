"""
Database utility functions.
Helper functions for MongoDB document conversion and common operations.
"""

from typing import Any, Optional, TypeVar, Type
from bson import ObjectId
from pydantic import BaseModel
from datetime import datetime

T = TypeVar("T", bound=BaseModel)


def to_str_id(doc: dict) -> dict:
    """
    Convert MongoDB document ObjectId to string.
    
    Args:
        doc: MongoDB document dictionary
        
    Returns:
        dict: Document with string _id
    """
    if doc is None:
        return None
    
    doc_copy = doc.copy()
    if "_id" in doc_copy and doc_copy["_id"] is not None:
        doc_copy["_id"] = str(doc_copy["_id"])
    
    return doc_copy


def docs_to_str_id(docs: list[dict]) -> list[dict]:
    """
    Convert list of MongoDB documents with ObjectId to string.
    
    Args:
        docs: List of MongoDB documents
        
    Returns:
        list[dict]: Documents with string _id
    """
    return [to_str_id(doc) for doc in docs if doc is not None]


def to_model(doc: dict, model_class: Type[T]) -> Optional[T]:
    """
    Convert MongoDB document to Pydantic model.
    Automatically handles ObjectId conversion.
    
    Args:
        doc: MongoDB document dictionary
        model_class: Target Pydantic model class
        
    Returns:
        Pydantic model instance or None
    """
    if doc is None:
        return None
    
    doc = to_str_id(doc)
    return model_class(**doc)


def docs_to_models(docs: list[dict], model_class: Type[T]) -> list[T]:
    """
    Convert list of MongoDB documents to Pydantic models.
    
    Args:
        docs: List of MongoDB documents
        model_class: Target Pydantic model class
        
    Returns:
        list: List of Pydantic model instances
    """
    return [to_model(doc, model_class) for doc in docs if doc is not None]


def serialize_datetime(dt: Optional[datetime]) -> Optional[str]:
    """
    Serialize datetime to ISO format string.
    
    Args:
        dt: datetime object or None
        
    Returns:
        ISO format string or None
    """
    return dt.isoformat() if dt else None


def enum_value(enum_val: Any) -> Any:
    """
    Get the value from an enum, handling both enum instances and raw values.
    
    Args:
        enum_val: Enum instance or raw value
        
    Returns:
        The enum value or the input if not an enum
    """
    return enum_val.value if hasattr(enum_val, "value") else enum_val


def build_filters(**kwargs: Any) -> dict:
    """
    Build MongoDB filter dictionary.
    
    Args:
        **kwargs: Filter key-value pairs (None values are skipped)
        
    Returns:
        dict: MongoDB filter dictionary
    """
    filters = {}
    
    for key, value in kwargs.items():
        if value is not None:
            # Handle enum values
            filters[key] = enum_value(value)
    
    return filters

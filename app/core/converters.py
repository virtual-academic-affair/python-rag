import re
from typing import Any

def to_snake(name: str) -> str:
    name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()

def normalize_to_snake(value: Any) -> Any:
    if isinstance(value, str):
        return to_snake(value)
    if isinstance(value, list):
        return [normalize_to_snake(v) for v in value]
    if isinstance(value, dict):
        return {to_snake(k): normalize_to_snake(v) for k, v in value.items()}
    return value

def convert_custom_metadata_to_snake(custom_metadata: dict) -> dict:
    if not custom_metadata:
        return {}
    return normalize_to_snake(custom_metadata)

def to_camel(name: str) -> str:
    components = name.split('_')
    if not components:
        return ""
    return components[0] + ''.join(x.title() for x in components[1:])

def convert_custom_metadata_to_camel(custom_metadata: dict) -> dict:
    if not custom_metadata:
        return {}
    return {to_camel(k): v for k, v in custom_metadata.items()}

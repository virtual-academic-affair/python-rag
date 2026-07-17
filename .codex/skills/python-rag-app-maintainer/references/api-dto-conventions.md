# API And DTO Conventions

Use this when changing routers, DTOs, response bodies, query/path params, Postman, or docs.

## Naming

- Public JSON uses `camelCase`.
- Python attributes use `snake_case`.
- DTO classes inherit `app.core.base_schema.BaseSchema`, which accepts snake_case or camelCase input and serializes aliases as camelCase.
- Do not manually camelize response dicts in routers. Prefer typed DTOs with `BaseSchema`.
- Route and query parameter names are public API too. Prefer camelCase names such as `{topicKey}` and `toRichText`.
- Multipart field names follow the actual endpoint declaration: DTO-backed `from_form` inputs accept schema aliases, while direct FastAPI `Form(...)` parameters use their declared names. Verify them against OpenAPI instead of assuming JSON camelCase rules.

## File Organization

- Create requests: `create_*.py`
- Update requests: `update_*.py`
- List/search responses: `list_*.py`, `search_*.py`
- Output schemas: `*_out.py`
- Import/review/debug DTOs get action-specific files.

## Conversion Pattern

Use typed converters like `FileMetadataResponse.from_model(...)` when internal data is snake_case or domain-object shaped.

```python
class YearRangeResponse(BaseSchema):
    from_year: int
    to_year: int

    @classmethod
    def from_model(cls, value):
        return cls(from_year=value.from_year, to_year=value.to_year)
```

Avoid router-level dict conversion for public response shape.

## API Contract Changes

When changing a route, request body, response body, query/path param, or SSE/event payload, update:

- `docs/api.txt`
- `docs/project-overview.txt`
- `docs/AI_Service.postman_collection.json`
- focused DTO/router/service tests

Preserve the current document layout and examples that remain valid. Patch the affected sections rather than replacing an entire document unless the user asks for a rewrite or the existing file is corrupted.

## Role Contract

Use `student | lecture | admin`. Do not use `lecturer` as an API role value.

"""RAG package.

Import concrete services from their subpackages to avoid eager-loading retrieval,
agent, and file router dependencies during ingestion-only imports.
"""

__all__: list[str] = []

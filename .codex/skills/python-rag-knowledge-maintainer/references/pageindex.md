# PageIndex Reference

Use this when touching PageIndex indexing artifacts, answering loops, tools, prompts, citations, or streaming events.

## Ingestion Side

- PageIndex artifacts are created from parsed Markdown during file ingestion.
- Artifact cleanup is started from app lifespan and is observable operational behavior.
- Description/TOC output can affect Corpus linking, rerank input, and prompt context.
- Do not put a transient ingestion filesystem path into the Redis document payload. Cache only stable metadata after Markdown upload and TOC upsert complete.

## Answering Side

- PageIndex answering runs only after FAQ answering is insufficient and candidate files exist.
- Non-stream answering returns final Markdown, sources, steps, token usage, and max-turn metadata through `RagQueryResult`.
- Stream answering forwards reasoning/tool/text/final events for chat stream adapters to encode as SSE.

## Metadata And Markdown Loading

- `_load_document_metadata(doc_id)` reads `pageindex:doc:{docId}` and falls back to `FileTocTree`. A valid payload includes `structure`, `doc_name`, `doc_description`, `line_count`, and `markdown_storage_path`.
- Structure-only callers do not inspect, touch, or download local Markdown. `get_document()` and `get_document_structure()` use metadata loading only.
- `_ensure_markdown_ready(doc_id, metadata)` is called only by page-content access. It uses the per-document `asyncio.Lock`, canonical `${PAGEINDEX_WORKSPACE}/{docId}.md`, TTL reuse with `touch()`, R2 download to a temporary file, and atomic replace.
- A missing or expired local Markdown file is reloaded from `markdown_storage_path`; R2 errors are explicit and must not become empty content.
- Old Redis metadata that lacks `markdown_storage_path` is a cache miss and must be reloaded from MongoDB.

## Boundaries

- PageIndex prompt builders and loops stay under `app/modules/rag/query/answering/pageindex_agent`.
- Citation/source helpers stay under `app/modules/rag/query/answering/pageindex_agent/citations`.
- Citation verification/source building belong in PageIndex answering code.
- HTML conversion, SSE JSON formatting, session persistence, and gRPC/email commits stay in service adapters.
- PageIndex Redis/local caches are best-effort for reads and exact-key eviction. Delete/purge evicts both `pageindex:doc:{docId}` and canonical local Markdown.

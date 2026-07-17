# Ingestion Flow Reference

Use this when touching parsing, indexing, metadata/linking, or code that prepares documents for retrieval.

## Main Flow

- File API creates/updates `FileDocument` and uploads content to R2.
- LlamaParse produces Markdown used for downstream indexing.
- PageIndex builds local/index artifacts, TOC, and description used by answering.
- Metadata extraction/linking must stay consistent with metadata filters used by query.
- `app/modules/rag/ingestion/corpus_linker.py` assigns Corpus topics used later for traversal seeds.
- File status/progress behavior is user-visible; preserve callbacks and WebSocket progress when changing ingestion.

## Boundaries

- File upload/list/update/delete API belongs to app-module maintenance.
- Parsing, PageIndex index creation, description generation, and CorpusLinker behavior belong here because they define what query can retrieve.
- Do not hardcode provider secrets; use settings/env.

## Contract With Query

- Query depends on stable file IDs, metadata, descriptions, PageIndex artifacts, and Corpus topic links.
- Topic assignment changes can alter retrieval recall; update Corpus/RAG tests when changing linker behavior.
- Description/content shape changes can affect Cohere rerank and PageIndex prompt quality.
- `index_md_content()` returns ingestion results but must not cache the transient parser path.
- Warm `pageindex:doc:{docId}` only after Markdown has been uploaded to R2 and the TOC document has been upserted with its stable `markdown_storage_path`.
- Successful READY/index/link changes invalidate the exact file entity, bump eligibility when visibility changes, and bump the Corpus revision when the indexed Corpus payload changes. Invalidation remains best-effort.

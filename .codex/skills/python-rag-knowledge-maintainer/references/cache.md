# RAG And PageIndex Cache Reference

Use this when touching Redis payloads, retrieval hydration, eligibility filtering, PageIndex metadata, local Markdown reuse, or mutation invalidation.

## Principles

- Redis and local Markdown are accelerators, never the source of truth.
- Redis read/write/`INCR`/`DELETE` failures must log a structured warning and fall back to MongoDB, R2, or the normal business path.
- Cache invalidation runs after a successful workflow and must not turn a successful mutation into a failure.
- Do not add request caches, filtered-snapshot caches, final-answer caches, distributed locks, Pub/Sub, wildcard `SCAN`, or presigned URL caching without a new explicit design.

## Keys And TTLs

Revision counters have no TTL:

```text
rag:revision:corpus
rag:revision:file_eligibility
rag:revision:faq_eligibility
```

Payload keys:

```text
rag:corpus:{corpusRevision}                                  # 300 seconds
rag:allowed:file:{revision}:{scope}:{metadataHash}           # 120 seconds
rag:allowed:faq:{revision}:{scope}:{metadataHash}            # 120 seconds
rag:file:{fileId}                                            # 600 seconds
rag:faq:{faqId}                                              # 600 seconds
pageindex:doc:{docId}                                        # 3600 seconds
${PAGEINDEX_WORKSPACE}/{docId}.md                            # 3600 seconds
```

- Redis keys contain neither `v2` nor the segment `:cache:`.
- Access scope is exactly `student` or `privileged`.
- Metadata hashes use canonical sorted JSON.
- Corpus and eligibility use revisions; entity hydration uses exact IDs.
- TTLs come from `RAG_CORPUS_CACHE_TTL_SECONDS`, `RAG_ALLOWED_IDS_CACHE_TTL_SECONDS`, `RAG_ENTITY_CACHE_TTL_SECONDS`, `PAGEINDEX_DOC_CACHE_TTL_SECONDS`, and `PAGEINDEX_MARKDOWN_CACHE_TTL_SECONDS`.
- Use the existing Redis primitives `mget_json`, `get_int`, `incr`, and `delete_many`; do not add `SETNX` unless a separately approved distributed-lock design requires it.

## Retrieval

- Cache typed Corpus nodes, then construct the filtered snapshot in memory.
- Cache allowed file and FAQ IDs independently because their eligibility mutations differ.
- Hydrate entity candidates with `MGET`; query MongoDB only for misses and retain candidate order.
- Entity payloads use strict schemas. Unknown fields in an old payload cause a miss and source reload.
- Never cache presigned R2 URLs.

## Invalidation

- File changes delete only `rag:file:{fileId}`; eligibility changes also bump `rag:revision:file_eligibility`.
- FAQ changes delete only `rag:faq:{faqId}`; eligibility changes also bump `rag:revision:faq_eligibility`.
- TOC changes invalidate the corresponding file entity and overwrite or evict `pageindex:doc:{docId}`.
- Topic mutations and successful payload reindex/unindex/backfill bump `rag:revision:corpus`.
- PageIndex delete/purge evicts the document Redis key and canonical local Markdown.
- Never invalidate entity caches with wildcard scans or a global entity revision.

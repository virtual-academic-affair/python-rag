# Corpus Retrieval Reference

Use this when touching Corpus traversal used by RAG, retrieval seeds, metadata prefilter, or hydration/rerank.

## Retrieval Responsibilities

- Corpus admin CRUD/tree/backfill APIs belong to app-module maintenance.
- Corpus traversal for RAG belongs here because it decides candidate FAQ/file seeds.
- Traversal should respect role and metadata prefilters before retrieval hydration.
- Candidate contracts should remain typed: file candidates expose file IDs; FAQ candidates expose FAQ IDs.

## Hydration And Rerank

- Hydrate FAQ docs before file candidates.
- Rerank FAQ docs separately from files with Cohere.
- If FAQ answering fully covers the question, stop before file hydration/rerank.
- Hydrate and rerank file candidates only when FAQ is insufficient.

## Failure Behavior

- Unexpected traversal or hydration failures should not be silently converted into "no documents" unless the path is explicitly debug/best-effort.
- Debug preview endpoints should depend on the same core retrieval/query flow where possible.

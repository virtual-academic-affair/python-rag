---
name: python-rag-knowledge-maintainer
description: Use when modifying, reviewing, or debugging python-rag knowledge ingestion and RAG query behavior, including rag/ingestion, rag/query, Corpus traversal for retrieval, PageIndex indexing or answering, Cohere rerank, FAQ answering in the pipeline, citations, chat/email RAG adapter behavior, or retrieval tests.
---

# Python RAG Knowledge Maintainer

Use this skill for changes that create, index, retrieve, rerank, or answer from the knowledge base.

## Workflow

1. Identify whether the change affects ingestion, query, or both.
2. Read the contract on both sides of the boundary: what ingestion writes/links and what query expects to retrieve.
3. Preserve the shared RAG pipeline: chat non-stream, chat stream, and email inquiry should route through `RagQueryPipeline`.
4. Keep adapters thin: chat/email services handle API formatting, rich text, SSE JSON, persistence, logging, and gRPC/email workflow side effects.
5. Verify with focused RAG/corpus/chat/email/FAQ tests.

## Read References As Needed

- Ingestion/indexing: `references/ingestion-flow.md`
- Query lifecycle: `references/query-flow.md`
- Corpus traversal/retrieval seeds: `references/corpus-retrieval.md`
- PageIndex indexing/answering: `references/pageindex.md`
- Test selection: `references/testing.md`

## Scope Boundary

- Use this skill for `app/modules/rag/ingestion`, `app/modules/rag/query`, retrieval hydration/rerank/traversal, PageIndex loops/tools/prompts/citations, FAQ answering in RAG, and chat/email adapter changes that alter answer source, citations, stream events, or rich text boundaries.
- Use `python-rag-app-maintainer` for normal CRUD/API/workflow work: file upload API, FAQ catalog/import, Corpus topic CRUD/tree/backfill, email gRPC side effects, forms, metadata schema API, and DTO-only changes.

## Guardrails

- FAQ should be attempted before file hydration/rerank; if FAQ fully answers, do not run PageIndex.
- File candidates and FAQ docs are reranked separately with Cohere.
- Do not move HTML conversion, SSE JSON formatting, persistence, gRPC commits, or email workflow side effects into `rag/query`.
- Keep role values as `student | lecture | admin`.

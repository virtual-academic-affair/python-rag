---
name: python-rag-app-maintainer
description: Use when modifying, reviewing, or debugging normal application modules in the python-rag FastAPI AI Service repo, including email workflows, file APIs, metadata, forms, FAQ catalog/import, Corpus admin APIs, chat/session APIs, DTOs, docs, Postman, or tests. Do not use for RAG ingestion/query internals; use python-rag-knowledge-maintainer instead.
---

# Python RAG App Maintainer

Use this skill for application-module maintenance in `python-rag`.

## Workflow

1. Orient with the narrowest useful files: router, service, DTO, repository/model, and tests for the touched module.
2. Preserve boundaries: routers handle HTTP/auth/error mapping; services handle workflows; repositories handle DB access; DTOs own public schema.
3. Validate API shape: public JSON is `camelCase`, Python internals are `snake_case`, DTOs inherit `BaseSchema`, and converters are preferred over ad hoc dict shaping.
4. Update `docs/api.txt`, `docs/project-overview.txt`, and `docs/AI_Service.postman_collection.json` when API, DTO, or workflow contracts change.
5. Verify with focused compile/tests or HTTP scripts.

## Read References As Needed

- Architecture/module boundaries: `references/architecture.md`
- API/DTO conventions: `references/api-dto-conventions.md`
- Test selection: `references/testing.md`

## Scope Boundary

- Use this skill for `email`, `files`, `metadata`, `forms`, FAQ CRUD/import/catalog, Corpus admin/debug APIs, chat/session APIs, startup/config, integrations, and protobuf-facing workflow work.
- Switch to `python-rag-knowledge-maintainer` for `rag/ingestion`, `rag/query`, Corpus traversal for retrieval, PageIndex indexing/answering, Cohere rerank, FAQ answering in the RAG pipeline, or chat/email changes that alter RAG lifecycle.

## Guardrails

- Keep role values as `student | lecture | admin`.
- Do not hardcode secrets or API keys.
- Repo-local Codex instructions live under `.codex` only.

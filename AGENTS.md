# Agent Guide For `python-rag`

This repo is a FastAPI AI service for academic email automation, document ingestion, FAQ/forms management, Corpus Tree retrieval, and shared RAG query answering.

## Project Map

- `app/main.py`: FastAPI app, lifespan startup/shutdown, Beanie document registration, RabbitMQ consumer startup, R2/Redis initialization, PageIndex artifact cleanup, and LLM client cleanup.
- `app/api/router.py`: aggregates all public routers under `/api`, plus root health route.
- `app/core`: settings, MongoDB connection, base Beanie repository/document, base API schema, auth dependencies, pagination, exceptions.
- `app/integrations`: external clients for R2 storage, RabbitMQ, Redis, gRPC, the shared LiteLLM gateway, LlamaParse, PageIndex, Cohere, and Excel helpers.
- `app/proto`: protobuf definitions and generated gRPC stubs for auth, message, inquiry, class registration, and common messages. HTTP/WebSocket JWT authentication is local HS256 and does not call the auth stub.
- `app/modules/email`: RabbitMQ ingest, label classification, workflow orchestration, WebSocket/email notifications, gRPC workflow calls.
- `app/modules/files`: file upload/list/update/delete/download, upload progress WebSocket, R2 upload, LlamaParse/PageIndex ingestion, TOC tree persistence.
- `app/modules/metadata`: hardened metadata value objects, schema endpoint, metadata validation, range-overlap filter builder.
- `app/modules/corpus`: Corpus Topic Tree admin/debug APIs, topic repository/service, traversal contracts, metadata/user-role prefilter.
- `app/modules/rag`: document parsing, corpus linking, and shared query pipeline for chat/email.
- `app/modules/chat`: non-stream chat, SSE chat stream, sessions/messages persistence, step formatting.
- `app/modules/faq`: FAQ CRUD/import/debug match and FAQ catalog support for RAG answering. Auto-synthesis, review candidates, and interaction logging have been removed.
- `app/modules/forms`: forms CRUD/import, rich text content/link handling.
- `scripts`: DB init, corpus/FAQ seed/backfill, snapshots, proto generation, and HTTP test scripts.
- `docs`: API reference, Postman collection, and architecture overview.

## Working Rules

- Read the relevant module before editing. Prefer `rg` and focused file reads.
- Keep changes scoped to the requested behavior. Do not revert unrelated user changes.
- Preserve existing module boundaries:
  - routers validate/auth/map HTTP;
  - services own business workflow;
  - repositories own MongoDB access;
  - DTOs own API request/response shape;
  - `app/modules/rag/query` owns shared chat/email RAG query lifecycle.
- Public API JSON is `camelCase`. Internal Python stays `snake_case`.
- API DTOs should inherit `BaseSchema` and use typed response schemas/converters, not ad hoc dict camelization in routers.
- DTO files are organized by action, matching existing modules: `create_*`, `update_*`, `list_*`, `*_out`, import/review/debug-specific files when needed.
- Settings and secrets belong in `app/core/config.py`, `.env`, and `.env.example`; never hardcode API keys in source/docs/tests.
- Integrations should stay thin clients. Business logic belongs in modules.
- Long-running work should preserve existing async/background behavior: RabbitMQ consumer, file progress WebSocket, PageIndex artifact cleanup, and ingestion callbacks.
- If an API, DTO, or response contract changes, update:
  - `docs/api.txt`
  - `docs/project-overview.txt`
  - `docs/AI_Service.postman_collection.json`
- Update `README.md` when setup, configuration, runtime architecture, or operator commands change.
- Preserve the existing structure and useful detail of documentation files. Make focused section edits; only replace a whole document when the user explicitly requests it or the file is demonstrably corrupted.
- Debug endpoint tuning and catalog limits stay as code-owned constants; do not expose them through `.env`, `.env.example`, or `Settings`.
- Do not commit secrets. `.env` may exist locally; never copy keys into docs, examples, tests, or source.

## Main Flows

- Email ingest: RabbitMQ message -> `EmailIngestConsumer` -> `EmailWorkflowOrchestrator` -> label classifier -> workflow service (`classRegistration`, `task`, `inquiry`, `other`) -> gRPC/email side effects.
- File ingest: upload API -> FileDocument/R2 -> LlamaParse Markdown -> PageIndex TOC/description -> CorpusLinker topic assignment -> READY status/progress events.
- Chat non-stream: router/session history -> `ChatService` -> `RagQueryPipeline.answer_chat` -> response DTO and persistence.
- Chat stream: router/session history -> `ChatStreamService` -> `RagQueryPipeline.stream_chat` -> SSE events -> final persistence.
- Email inquiry: inquiry workflow -> `RagQueryPipeline.answer_email` -> original citation behavior -> gRPC draft/response workflow.
- FAQ debug/answering: FAQ catalog retrieval -> LLM reads one or more FAQ docs -> answer only if FAQ fully covers the question.
- Corpus retrieval: metadata/user-role prefilter -> Corpus Tree traversal -> typed FAQ/file seeds -> FAQ-first context, then file context only when needed.

## RAG And Corpus Rules

- Chat non-stream, chat stream, and email inquiry use the shared `RagQueryPipeline`.
- Chat/email service layers stay adapters for API formatting, persistence, SSE/gRPC/email workflow, and rich text conversion.
- FAQ is handled before file hydration/rerank. If FAQ answering fully covers the question, do not hydrate/rerank files.
- File candidates and FAQ docs are reranked separately with Cohere.
- `app.modules.corpus.contracts.FaqCandidate` is a typed retrieval seed, not a retired synthesis/review candidate.
- PageIndex answering code belongs under `app/modules/rag/query/answering/pageindex_agent`.
- FAQ answering code belongs under `app/modules/rag/query/answering/faq_answering`.
- RAG Redis caching is best-effort: Redis failures must fall back to MongoDB/source data and must not fail business queries or mutations.
- Corpus and eligibility caches use revisions; file/FAQ entity caches use exact IDs and partial `MGET` hydration while preserving candidate order.
- Do not cache final answers, analyzer/traversal LLM output, Cohere rerank results, presigned R2 URLs, or whole request-filtered snapshots.
- Role contract is `student | lecture | admin`; do not introduce `lecturer` as a role value.

## API And DTO Rules

- Use `BaseSchema` for API request/response DTOs so aliases serialize as camelCase.
- Use typed converters like `FileMetadataResponse.from_model(...)` for snake_case/domain-model input that must become camelCase JSON.
- Do not return raw dicts for public API when a typed DTO is reasonable.
- Route params and query params are public API too; use camelCase aliases or path names such as `{topicKey}`, `includeLeafIds`.
- REST and first-message WebSocket authentication verify JWT locally with HS256 using `JWT_SECRET`, `JWT_TOKEN_AUDIENCE`, and `JWT_TOKEN_ISSUER`.
- Keep Mongo/document fields stable unless a migration is explicitly planned.

## Verification

Use the narrowest meaningful tests first, then broader tests for shared behavior:

- Corpus/RAG query changes:
  - `.venv/bin/python -m pytest tests/modules/corpus tests/modules/rag`
- Chat changes:
  - `.venv/bin/python -m pytest tests/modules/chat tests/modules/rag`
- Email inquiry changes:
  - `.venv/bin/python -m pytest tests/modules/email tests/modules/rag`
- FAQ changes:
  - `.venv/bin/python -m pytest tests/modules/faq tests/modules/rag`
- File ingestion/metadata changes:
  - `.venv/bin/python -m pytest tests/modules/files tests/modules/corpus tests/modules/rag`
- Forms or metadata API changes:
  - `bash scripts/test/test_forms.sh`
  - `bash scripts/test/test_metadata.sh`
- Email classification changes:
  - `bash scripts/test/test_classification.sh`
- Broad regression after shared contract changes:
  - `.venv/bin/python -m pytest tests/modules/corpus tests/modules/rag tests/modules/chat tests/modules/email tests/modules/faq tests/modules/files`
- Compile focused modules after refactors:
  - `.venv/bin/python -m compileall -q app/modules/corpus app/modules/rag app/modules/chat app/modules/email app/modules/faq app/modules/files app/modules/forms app/modules/metadata`

## Local Skills

Use repo-local Codex skills by task area:

- App/API/module CRUD or workflow work: `./.codex/skills/python-rag-app-maintainer/SKILL.md`
- Ingestion/query/retrieval/answering work: `./.codex/skills/python-rag-knowledge-maintainer/SKILL.md`
- If a task touches both areas, use both skills and read only the references needed for the change.

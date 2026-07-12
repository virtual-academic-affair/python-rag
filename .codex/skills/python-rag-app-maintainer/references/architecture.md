# App Architecture Reference

Use this when changes touch module boundaries, startup behavior, public APIs, integrations, or more than one non-RAG module.

## Runtime Shape

- `app/main.py` creates the FastAPI app, registers Beanie documents, initializes MongoDB, checks R2, starts RabbitMQ email ingestion when enabled, creates the email workflow orchestrator, warms optional Redis, and starts PageIndex artifact cleanup.
- `app/api/router.py` aggregates module routers under `/api`; the root health route is not module-owned.
- `app/core` contains settings, auth dependencies, MongoDB connection, base Beanie repository/document, `BaseSchema`, pagination, app exceptions, and shared HTTP/WebSocket helpers such as first-message WebSocket authentication.
- `app/integrations` contains thin external clients for R2/storage, RabbitMQ, Redis, gRPC, Gemini, LlamaParse, PageIndex, Cohere, and Excel helpers. Keep business rules in modules.
- `app/proto` contains protobuf definitions and generated gRPC stubs for auth, message, inquiry, class registration, and common messages.

## App Modules

- `app/modules/email`: RabbitMQ email ingest, label classification, workflow orchestration, WebSocket/email notifications, and gRPC workflow side effects. Email WebSocket routers should reuse shared WebSocket auth helpers and keep protocol handling local.
- `app/modules/files`: file upload/list/update/delete/download, batch upload DTOs, upload progress WebSocket, R2 storage, and file status APIs. HTTP-facing upload/list/download orchestration belongs in file API services; parsing/indexing behavior that affects retrieval belongs to the knowledge skill.
- `app/modules/metadata`: metadata value objects, schema endpoint, extraction helpers, validation, parsers, and overlap/range filter construction.
- `app/modules/corpus`: Corpus Topic Tree admin/debug APIs, topic service/repository, typed DTOs, topic merge/backfill. Backfill job orchestration and debug preview mapping belong in corpus services; traversal behavior used by RAG belongs to the knowledge skill.
- `app/modules/chat`: chat routes, sessions/messages persistence, response DTOs, and step formatting. Conversation/session orchestration belongs in chat services; RAG pipeline behavior belongs to the knowledge skill.
- `app/modules/faq`: FAQ CRUD/search/import, catalog management, candidate synthesis, and interaction logs. Import parsing/validation belongs in FAQ import services; FAQ answering in the RAG pipeline belongs to the knowledge skill.
- `app/modules/forms`: form CRUD/list/import and rich text content/link handling. Import parser selection, row validation, and bulk upsert orchestration belong in form import services.

## Boundaries

- Routers stay thin: auth dependencies, public parameter declarations, response models, HTTP exception mapping, and wire concerns such as `StreamingResponse`, `BackgroundTasks`, and WebSocket accept/send/receive loops.
- Services own business workflow and module-local side effects. Use focused API/workflow services when router logic would otherwise grow: file API/debug services, FAQ/Form import services, Corpus debug/job services, and chat conversation/session services.
- Repositories own persistence queries and document mutations.
- DTOs own public request/response shape and API naming.
- Background work and WebSocket progress are observable behavior; preserve them when refactoring workflow paths. Shared WebSocket authentication belongs in `app/core/websocket_auth.py`; module routers still own the WebSocket protocol shape and notifier connect/disconnect.

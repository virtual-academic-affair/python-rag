# PageIndex Reference

Use this when touching PageIndex indexing artifacts, answering loops, tools, prompts, citations, or streaming events.

## Ingestion Side

- PageIndex artifacts are created from parsed Markdown during file ingestion.
- Artifact cleanup is started from app lifespan and is observable operational behavior.
- Description/TOC output can affect Corpus linking, rerank input, and prompt context.

## Answering Side

- PageIndex answering runs only after FAQ answering is insufficient and candidate files exist.
- Non-stream answering returns final Markdown, sources, steps, token usage, and max-turn metadata through `RagQueryResult`.
- Stream answering forwards reasoning/tool/text/final events for chat stream adapters to encode as SSE.

## Boundaries

- PageIndex prompt builders and loops stay under `app/modules/rag/query/answering/pageindex_agent`.
- Citation/source helpers stay under `app/modules/rag/query/answering/pageindex_agent/citations`.
- Citation verification/source building belong in PageIndex answering code.
- HTML conversion, SSE JSON formatting, session persistence, and gRPC/email commits stay in service adapters.

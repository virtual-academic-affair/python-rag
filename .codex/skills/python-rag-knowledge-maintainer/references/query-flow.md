# Query Flow Reference

Use this when touching chat/email RAG behavior, analyzers, retrieval, rerank, FAQ answering, or PageIndex answering.

## Shared Query Pipeline

`app/modules/rag/query` owns the shared query lifecycle for:

- chat non-stream;
- chat stream;
- email inquiry.

Service layers remain adapters for API formatting, rich text conversion, SSE JSON, persistence, logging, gRPC, and email workflow behavior.

## Retrieval Order

1. Analyze chat/email context as configured by behavior.
2. Traverse Corpus Tree to obtain typed file/FAQ seeds.
3. Hydrate and Cohere-rerank FAQ docs first.
4. Let the FAQ answering LLM read one or more FAQ docs.
5. If FAQ fully answers the question, return `source="faq"` without file hydration/rerank.
6. Otherwise hydrate and Cohere-rerank file candidates.
7. Run PageIndex answering if files exist; otherwise return no-candidate fallback.

## Chat And Email Differences

- Non-stream chat returns final Markdown and may be converted to HTML by chat service when `toRichText=True`.
- Stream chat forwards reasoning/tool/text/final events and never performs rich text conversion.
- Email inquiry uses `RagQueryPipeline.answer_email`, keeps gRPC/email side effects outside `rag/query`, and uses original citation behavior when requested.

## Location Rules

- Behaviors: `app/modules/rag/query/behaviors.py`
- Contracts: `app/modules/rag/query/contracts.py`
- Analyzers: `app/modules/rag/query/analyzer`
- Retrieval: `app/modules/rag/query/retrieval`
- FAQ answering: `app/modules/rag/query/answering/faq_answering`
- PageIndex answering agent: `app/modules/rag/query/answering/pageindex_agent`

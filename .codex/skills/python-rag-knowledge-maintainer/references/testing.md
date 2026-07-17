# Knowledge Testing Reference

Use focused tests first; run broader tests when changing shared contracts.

## Compile

```bash
.venv/bin/python -m compileall -q app/modules/rag app/modules/corpus app/modules/chat app/modules/email app/modules/faq app/modules/files
```

## Targeted Tests

- RAG query pipeline:
  ```bash
  .venv/bin/python -m pytest tests/modules/rag
  ```
- RAG/PageIndex cache changes:
  ```bash
  .venv/bin/python -m pytest tests/modules/rag tests/integrations/test_pageindex_document_cache.py
  ```
- Corpus traversal/retrieval:
  ```bash
  .venv/bin/python -m pytest tests/modules/corpus tests/modules/rag
  ```
- FAQ answering in pipeline:
  ```bash
  .venv/bin/python -m pytest tests/modules/faq tests/modules/rag
  ```
- Chat RAG adapters:
  ```bash
  .venv/bin/python -m pytest tests/modules/chat tests/modules/rag
  ```
- Email inquiry RAG:
  ```bash
  .venv/bin/python -m pytest tests/modules/email tests/modules/rag
  ```
- File ingestion affecting retrieval:
  ```bash
  .venv/bin/python -m pytest tests/modules/files tests/modules/corpus tests/modules/rag
  ```

## Broad Regression

```bash
.venv/bin/python -m pytest tests/modules/corpus tests/modules/rag tests/modules/chat tests/modules/email tests/modules/faq tests/modules/files
```

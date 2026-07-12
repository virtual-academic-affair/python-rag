# App Testing Reference

Use focused checks first, then broader regression for shared contracts.

## Compile

```bash
.venv/bin/python -m compileall -q app/modules/chat app/modules/email app/modules/faq app/modules/files app/modules/forms app/modules/metadata app/modules/corpus app/core app/integrations
```

## Targeted Tests And Scripts

- Chat/session API:
  ```bash
  .venv/bin/python -m pytest tests/modules/chat
  bash scripts/test/test_chat.sh
  bash scripts/test/test_chat_sessions.sh
  ```
- Email workflows/classification:
  ```bash
  .venv/bin/python -m pytest tests/modules/email
  bash scripts/test/test_classification.sh
  ```
- FAQ catalog/import:
  ```bash
  .venv/bin/python -m pytest tests/modules/faq
  bash scripts/test/test_faq.sh
  ```
- Files API:
  ```bash
  .venv/bin/python -m pytest tests/modules/files
  bash scripts/test/test_files.sh
  ```
- Forms and metadata:
  ```bash
  .venv/bin/python -m pytest tests/modules/forms
  bash scripts/test/test_forms.sh
  bash scripts/test/test_metadata.sh
  ```
- Corpus admin/debug API:
  ```bash
  .venv/bin/python -m pytest tests/modules/corpus
  ```
- Shared WebSocket/auth helpers:
  ```bash
  .venv/bin/python -m pytest tests/core/test_websocket_auth.py
  ```

## Broad Regression

```bash
.venv/bin/python -m pytest tests/modules/chat tests/modules/email tests/modules/faq tests/modules/files tests/modules/forms tests/modules/corpus tests/core/test_websocket_auth.py
```

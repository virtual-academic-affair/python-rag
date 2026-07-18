# AI Service — FastAPI Email Automation & RAG

Version `5.0.0`. Service này xử lý email nghiệp vụ giáo vụ, quản lý kho tài liệu/FAQ/biểu mẫu và cung cấp RAG dùng chung cho chat, chat stream và email inquiry.

## Chức năng chính

- Email automation: nhận message từ RabbitMQ, phân loại `classRegistration | inquiry`, trích xuất payload và gọi workflow gRPC khi được bật.
- File ingestion: lưu file gốc trên R2, dùng LlamaParse tạo Markdown, PageIndex tạo TOC/description và CorpusLinker gán tài liệu vào cây chủ đề.
- RAG query: phân tích câu hỏi, duyệt Corpus Tree, thử trả lời bằng FAQ trước; chỉ hydrate/rerank file và chạy PageIndex agent khi FAQ chưa đủ.
- Chat: non-stream, SSE stream, session/message persistence, archive/unarchive/rename/delete và `faqRecommendation` để frontend prefill form tạo FAQ thủ công.
- Catalog: FAQ CRUD/import, Forms CRUD/import, file soft-delete/restore/purge và Corpus admin APIs.
- Cache: Redis cache cho Corpus nodes, allowed IDs, file/FAQ hydration và PageIndex metadata; Markdown được cache ở local workspace.


## Kiến trúc RAG hiện tại

```text
Question / email
      |
      v
Query analyzer (chat hoặc email)
      |
      v
Corpus Tree traversal + metadata/role prefilter
      |
      +--> FAQ seeds --> hydrate + Cohere rerank --> FAQ answering
      |                                           |
      |                                           +--> đủ bao phủ: trả source="faq"
      |
      +--> file seeds --> hydrate + Cohere rerank --> PageIndex agent
                                                  |
                                                  +--> answer + citations
```

Các nguyên tắc quan trọng:

- Role hợp lệ: `student | lecture | admin`.
- Student không được thấy file/FAQ `lecturerOnly=true`.
- FAQ và file được rerank riêng, không trộn chung candidate pool.
- Nếu không có candidate phù hợp, pipeline trả `source="bypass"`.
- Chat small talk có thể trả trực tiếp với `source="llm"` mà không chạy retrieval.
- Bot chỉ trả lời nội dung thuộc phạm vi Giáo vụ đại học; câu hỏi ngoài phạm vi được từ chối ngắn gọn và hướng người dùng về các chủ đề học vụ liên quan.
- Redis là best-effort: lỗi Redis không được làm query hoặc mutation nghiệp vụ thất bại.

## Công nghệ

| Thành phần | Công nghệ |
|---|---|
| API/DTO | FastAPI, Pydantic v2 |
| MongoDB ODM | Motor, Beanie |
| LLM gateway | LiteLLM, model cấu hình bằng `LLM_MODEL` |
| Rerank | Cohere Rerank |
| Parsing/indexing | LlamaParse, PageIndex |
| Object storage | S3-compatible storage / Cloudflare R2 |
| Cache | Redis + local Markdown workspace |
| Messaging/RPC | RabbitMQ, gRPC |

## Cấu trúc repository

```text
app/
├── api/router.py                 # Tổng hợp REST và WebSocket routers
├── core/                         # Settings, auth, DB, base DTO/document/repository
├── integrations/                 # LLM, Cohere, LlamaParse, PageIndex, Redis, R2, RabbitMQ, gRPC
├── modules/
│   ├── chat/                     # Chat APIs, session/message persistence, SSE adapter
│   ├── corpus/                   # Topic CRUD, tree, backfill, traversal contracts/debug
│   ├── email/                    # Consumer, classification, workflows, progress WebSocket
│   ├── faq/                      # FAQ catalog/import
│   ├── files/                    # File API, upload workflow, TOC tree, progress WebSocket
│   ├── forms/                    # Forms catalog/import
│   ├── metadata/                 # Typed metadata schema/filtering
│   └── rag/                      # Ingestion và shared query pipeline
├── proto/                        # Protobuf definitions và generated stubs
└── utils/                        # Shared formatting/text/retry helpers

docs/
├── api.txt                       # REST/WebSocket contract
├── project-overview.txt          # Kiến trúc và runtime workflows
└── AI_Service.postman_collection.json

scripts/
├── init_db.py
├── seed_corpus.py
├── seed_faqs.py
├── snapshot.py
└── test/
```

## Cài đặt

Yêu cầu Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Các biến bắt buộc hoặc thường dùng:

- `LLM_API_KEY`: API key của provider trong `LLM_MODEL`.
- `LLM_MODEL`: tên model có provider prefix, mặc định `gemini/gemini-2.5-flash`.
- `MONGODB_URL`, `MONGODB_DB_NAME`.
- `LLAMA_CLOUD_API_KEY` cho ingestion.
- `R2_ENDPOINT`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET_NAME`.
- `JWT_SECRET`, `JWT_TOKEN_AUDIENCE`, `JWT_TOKEN_ISSUER`.
- `COHERE_API_KEY` nếu bật rerank.
- `REDIS_URL`; có thể tắt Redis bằng `REDIS_ENABLED=false`.

## Chạy service

```bash
python run.py
```

Swagger UI: `http://localhost:8000/docs`
Health check: `GET /health`

JWT được xác thực cục bộ bằng HS256. REST client gửi:

```http
Authorization: Bearer <token>
```

WebSocket progress phải gửi JWT làm message đầu tiên sau khi kết nối:

- `/api/files/progress/{clientId}`: mọi user hợp lệ.
- `/api/email/progress/{clientId}`: chỉ admin.

## Dữ liệu và maintenance

Khởi tạo lại database/storage là thao tác phá huỷ dữ liệu:

```bash
python scripts/init_db.py --skip-confirm
```

Seed riêng:

```bash
python scripts/seed_corpus.py
python scripts/seed_faqs.py --file scripts/sample_faqs.json
```

Snapshot:

```bash
python scripts/snapshot.py export scripts/uploads_result/rag_backup.json
python scripts/init_db.py --restore scripts/uploads_result/rag_backup.json
```

## Kiểm thử

```bash
.venv/bin/python -m compileall -q app scripts
.venv/bin/python -m pytest tests/modules/corpus tests/modules/rag tests/modules/chat tests/modules/email tests/modules/faq tests/modules/files
bash scripts/test/run_all.sh
```

Xem [docs/api.txt](docs/api.txt) cho contract API và [docs/project-overview.txt](docs/project-overview.txt) cho kiến trúc chi tiết.

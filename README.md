# Email AI Service

**Version 3.0.0** — Microservice hợp nhất giữa **phân loại email tự động** và **tìm kiếm tài liệu dựa trên RAG** cho hệ thống hỗ trợ sinh viên đại học.

---

## Tổng quan

Service nhận email từ RabbitMQ, tự động phân loại và xử lý:

- **classRegistration** → trích xuất thông tin đăng ký học phần
- **inquiry** → soạn email trả lời tự động bằng RAG (tìm trong tài liệu nội bộ)
- **task** → ghi nhận nhiệm vụ hành chính, gọi gRPC TaskService
- **other** → các email không thuộc danh mục trên

Ngoài ra, service cung cấp API quản lý kho tài liệu (upload, tìm kiếm, chat RAG).

---

## Tech Stack

| Thành phần | Công nghệ | Phiên bản |
|---|---|---|
| Web framework | FastAPI | 0.125.0 |
| AI / LLM | Google Gemini (google-genai) | 1.56.0 |
| Database | MongoDB (Motor async) | 3.3.2 |
| Object storage | MinIO (S3-compatible) | 7.2.3 |
| Message broker | RabbitMQ (pika) | 1.3.2 |
| gRPC client | grpcio + grpcio-tools | 1.71.0 |
| Config | pydantic-settings | 2.x |

---

## Cấu trúc thư mục

```
email_langchain/
├── app/
│   ├── main.py                         # FastAPI app + lifespan
│   ├── api/
│   │   ├── router.py                   # Tổng hợp tất cả router
│   │   └── endpoints/
│   │       └── classification.py       # POST /process, /api/test/classification/ingested
│   ├── core/
│   │   ├── config.py                   # Settings từ .env (pydantic-settings)
│   │   ├── database.py                 # MongoDB connection (Motor)
│   │   ├── exceptions.py               # Custom exception hierarchy
│   │   └── prompts.py                  # System prompts cho Gemini
│   ├── dependencies/
│   │   └── auth.py                     # require_auth, require_admin (FastAPI Depends)
│   ├── models/
│   │   ├── database.py                 # MongoDB document models (dataclass)
│   │   ├── enums.py                    # Enums dùng trong nghiệp vụ
│   │   └── schemas.py                  # Pydantic request/response schemas
│   ├── proto/
│   │   ├── auth/                       # Compiled protobuf auth
│   │   ├── class_registration/         # Compiled protobuf class registration
│   │   ├── email/                      # Compiled protobuf email draft
│   │   ├── label/                      # Compiled protobuf label update
│   │   ├── task/                       # Compiled protobuf task
│   │   ├── *.proto                     # Source proto files
│   │   └── common.proto
│   ├── repositories/
│   │   ├── base.py                     # BaseRepository (CRUD generic)
│   │   ├── file_repository.py
│   │   ├── store_repository.py
│   │   └── metadata_repository.py
│   ├── services/
│   │   ├── integrations/
│   │   │   └── grpc_client.py           # Shared gRPC client (label/task/class_reg)
│   │   ├── messaging/
│   │   │   ├── rabbitmq_service.py      # RabbitMQ connection
│   │   │   └── email_ingest_consumer.py # Consumer thread
│   │   ├── orchestration/
│   │   │   ├── email_workflow_orchestrator.py  # Router email → workflow
│   │   │   ├── llm_factory.py
│   │   │   ├── classification/
│   │   │   │   └── label_classifier_service.py # Gemini classify
│   │   │   └── workflows/
│   │   │       ├── class_registration_service.py
│   │   │       ├── inquiry_service.py
│   │   │       ├── task_service.py
│   │   │       └── other_service.py
│   │   └── rag/
│   │       ├── gemini_service.py       # Gemini client (chat + draft)
│   │       ├── file_service.py         # Upload file → MinIO + Gemini
│   │       ├── store_service.py        # Quản lý Gemini File Search store
│   │       ├── metadata_service.py     # CRUD + validate metadata types
│   │       └── email_draft_service.py  # Hàm soạn email trả lời (RAG)
│   ├── storage/
│   │   └── minio_client.py             # MinIO client singleton
│   └── utils/
│       ├── filter_builder.py           # Build Gemini filter string
│       ├── store_utils.py              # Resolve store ID, convert filter
│       ├── file_utils.py               # Validate size, extension, MIME
│       ├── db_utils.py                 # MongoDB helper
│       └── pagination.py               # Paginated response helper
├── config/
│   └── settings.py                     # Base config
├── scripts/
│   ├── gen_proto.py                    # Generate protobuf stubs
│   ├── init_db.py                      # Khởi tạo index MongoDB
│   ├── seed_metadata.py                # Seed 3 metadata types hệ thống
│   ├── test_all_apis.sh                # Script test nhanh API
│   └── uploads/                        # Dữ liệu upload mẫu
├── docs/
│   ├── AI_Service.postman_collection.json
│   ├── api.txt
│   └── project-overview.txt
├── docker-compose.yml
├── Dockerfile
├── run.py                              # Entry point (uvicorn)
└── requirements.txt
```

---

## Cài đặt & Chạy

### Yêu cầu

- Python 3.10+
- Docker & Docker Compose
- MongoDB
- Google Gemini API Key — https://aistudio.google.com/apikey

### 1. Tạo môi trường ảo và cài dependencies

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Cấu hình môi trường

Tạo file `.env` (xem phần Environment Variables bên dưới).

### 3. Khởi động Docker services

`docker-compose.yml` chứa các services: **MinIO** và **RabbitMQ**.

```bash
# Chỉ khởi động MinIO (nếu RabbitMQ đã chạy riêng)
./start.sh

# Khởi động tất cả – MinIO + RabbitMQ
./start.sh --all
```

Dừng services:

```bash
./stop.sh
./stop.sh --all
```

### 4. Seed dữ liệu ban đầu

```bash
python scripts/init_db.py
python scripts/seed_metadata.py
```

### 5. Chạy service

```bash
python run.py
```

---

## Các điểm truy cập

| Dịch vụ | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |
| RabbitMQ Management | http://localhost:15672 |

---

## API Endpoints

### Email Classification
```
POST /process
POST /api/test/classification/ingested
```

### Chat (RAG)
```
POST /api/chat/query
POST /api/chat/stream
```

### Files
```
POST   /api/files
POST   /api/files/batch
GET    /api/files
GET    /api/files/{id}
DELETE /api/files/{id}
DELETE /api/files/bulk
```

### Stores
```
POST   /api/stores
GET    /api/stores
GET    /api/stores/{id}
PATCH  /api/stores/{id}
DELETE /api/stores/{id}
```

### Metadata
```
POST   /api/metadata
GET    /api/metadata
GET    /api/metadata/{key}
PATCH  /api/metadata/{key}
DELETE /api/metadata/{key}
```

---

## Luồng xử lý Email

```
NestJS Backend
     │
     │  (RabbitMQ message)
     ▼
EmailIngestConsumer (thread riêng)
     │
     ▼
EmailWorkflowOrchestrator.process_request()
     │
     ├─ LabelClassifierService (Gemini) → "classRegistration" / "inquiry" / "task" / "other"
     │
     ├─[classRegistration]─▶ ClassRegistrationService → trích xuất JSON + gRPC
     │
     ├─[inquiry]───────────▶ InquiryService.process()
     │                              ├── draft_inquiry_email_reply() (RAG)
     │                              └── GrpcNestEmailClient.create_draft()
     │
     ├─[task]──────────────▶ TaskService → extract payload + GrpcClient.create_task()
     │
     └─[other]─────────────▶ OtherService (log)
```

---

## Giao tiếp với nest-api

### Chiều nhận (RabbitMQ)

nest-api gửi email đến service qua queue `email.ingest`:

```json
{
  "pattern": "ingested",
  "data": {
    "messageId": 123,
    "subject": "Đăng ký môn học",
    "senderEmail": "student@example.com",
    "senderName": "Nguyễn Văn A",
    "content": "..."
  }
}
```

### Chiều gửi (gRPC)

Service gọi nest-api qua gRPC:

| Service | Method | Khi nào |
|---|---|---|
| AuthService | VerifyToken(token) | Mọi request cần auth |
| EmailService | CreateDraft(messageId, draftSubject, draftBody) | Sau khi soạn xong draft inquiry |
| TaskService | Create(CreateTaskRequest) | Khi label = task |
| ClassRegistrationService | Create(CreateRegistrationRequest) | Khi label = classRegistration |

Proto được quản lý trong `app/proto/*.proto` và generated vào `app/proto/<service>/*_pb2.py`.

---

## Environment Variables

```env
# === AI ===
GOOGLE_API_KEY=           # Gemini API key
LLM_MODEL=gemini-2.5-flash
GEMINI_MODEL=gemini-2.5-flash

# === Server ===
HOST=0.0.0.0
PORT=8000
DEBUG=false
RELOAD=true

# === MongoDB ===
MONGODB_URL=mongodb+srv://...
MONGODB_DB_NAME=email_ai_service

# === MinIO ===
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=documents
MINIO_SECURE=false

# === RabbitMQ ===
RABBITMQ_ENABLED=true
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_INGEST_QUEUE=email.ingest

# === gRPC (nest-api) ===
GRPC_URL=localhost:5000
GRPC_ENABLED=true
GRPC_TIMEOUT_SECONDS=15

# === Upload ===
MAX_FILE_SIZE_MB=50
ALLOWED_EXTENSIONS=pdf,docx,doc,txt,md,html
```

---

## Scripts

```bash
python scripts/gen_proto.py
python scripts/init_db.py
python scripts/seed_metadata.py
```

---

## License

[Add your license here]


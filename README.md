# Email AI Service

**Version 3.0.0** — Microservice hợp nhất giữa **phân loại email tự động** và **tìm kiếm tài liệu dựa trên RAG** cho hệ thống hỗ trợ sinh viên đại học.

---

## Tổng quan

Service nhận email từ RabbitMQ, tự động phân loại và xử lý:

- **classRegistration** → trích xuất thông tin đăng ký học phần
- **inquiry** → soạn email trả lời tự động bằng RAG (truy vấn từ kho tài liệu học thuật/quy chế)
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
| Object storage | R2 (S3-compatible) | 7.2.3 |
| Message broker | RabbitMQ (pika) | 1.3.2 |
| gRPC client | grpcio + grpcio-tools | 1.71.0 |
| Config | pydantic-settings | 2.x |

---

## Cấu trúc thư mục

```
python-rag/
├── app/
│   ├── main.py                         # FastAPI app + lifespan
│   ├── api/
│   │   ├── router.py                   # Tổng hợp tất cả router
│   │   └── endpoints/
│   │       ├── classification.py       # POST /process, /api/test/classification/ingested
│   │       ├── stores.py               # CRUD store + Gemini sync
│   │       ├── files.py                # Upload, download, retry, batch, delete
│   │       ├── metadata.py             # CRUD metadata types
│   │       └── chat.py                 # POST /api/chat/query, /api/chat/stream
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
│   │   ├── inquiry/                    # Compiled protobuf inquiry draft
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
│   │   │   └── grpc_client.py           # Shared gRPC client
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
│   │       ├── chat_service.py         # POST /api/chat/query, /api/chat/stream
│   │       ├── email_draft_service.py  # Hàm soạn email trả lời (RAG)
│   │       ├── file_service.py         # Upload file → R2 + Gemini
│   │       ├── gemini_client.py        # Gemini client singleton
│   │       ├── metadata_service.py     # CRUD + validate metadata types
│   │       ├── store_service.py        # Quản lý Gemini File Search store
│   │       └── utils/
│   │           ├── file_utils.py       # Validate size, extension, MIME
│   │           ├── filter_builder.py   # Build Gemini filter string
│   │           ├── gemini_rag_utils.py # Helpers cho Gemini RAG
│   │           └── store_utils.py      # Resolve store ID, convert filter
│   ├── storage/
│   │   └── r2_client.py             # R2 client singleton
│   └── utils/
│       ├── db_utils.py                 # MongoDB helper
│       └── pagination.py               # Paginated response helper
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

`docker-compose.yml` chứa các services: **R2** và **RabbitMQ**.

```bash
# Chỉ chạy APP (dùng nếu RabbitMQ đã chạy từ nest-api)
./start.sh

# Chạy APP + RabbitMQ
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
| R2 Console | http://localhost:9001 |
| RabbitMQ Management | http://localhost:15672 |

---
 
## Authentication & Permissions
 
Hệ thống sử dụng JWT Bearer token được xác thực qua gRPC AuthService. Có hai mức độ phân quyền chính:
 
- **User (`require_auth`)**: Bất kỳ người dùng nào có token hợp lệ.
- **Admin (`require_admin`)**: Người dùng có token hợp lệ và có role là "admin".
 
### Summary Table
 
| API Category | Method | Endpoint | Permission | Note |
|---|---|---|---|---|
| **Chat (RAG)** | POST | `/api/chat/query` | Public/Implicit | Tùy vào cấu hình auth filter |
| | POST | `/api/chat/stream` | Public/Implicit | Tùy vào cấu hình auth filter |
| File Search (GET) | `GET /api/files` | User (Auth) | `student`: student only; `lecture`: lecture+student; `admin`: all. Ngoài ra ẩn các meta fields dựa vào `visibleRoles` (Admin không bypass bộ lọc này) |
| File Search (POST) | `POST /api/files` | Admin | Requires metadata: `access_scope` (admin, lecture, student), ... |
| | POST | `/api/files/batch` | **Admin** | Batch upload |
| | DELETE | `/api/files/{fileId}` | **Admin** | Xóa file |
| | DELETE | `/api/files/all` | **Admin** | Xóa tất cả file |
| **Stores** | GET | `/api/stores` | **Admin** | Liệt kê store |
| | GET | `/api/stores/{storeId}` | **Admin** | Chi tiết store |
| | POST | `/api/stores` | **Admin** | Tạo store |
| | PATCH | `/api/stores/{storeId}` | **Admin** | Cập nhật store |
| | DELETE | `/api/stores/{storeId}` | **Admin** | Xóa store |
| | POST | `/api/stores/{storeId}/sync` | **Admin** | Đồng bộ store |
| **Metadata** | GET | `/api/metadata` | **User** | Liệt kê metadata types; ẩn các values không có `visibleRoles` phù hợp với User/Admin |
| | POST | `/api/metadata` | **Admin** | Tạo metadata field type (ví dụ: Năm học, Khóa); `visibleRoles` là bắt buộc cho từng `allowedValue` |
| | GET | `/api/metadata/{key}` | **User** | Chi tiết metadata type |
| | PATCH | `/api/metadata/{key}` | **Admin** | Cập nhật metadata type (không sửa allowed values) |
| | POST | `/api/metadata/{key}/values` | **Admin** | Thêm allowed value mới vào metadata type |
| | PATCH | `/api/metadata/{key}/values/{value}` | **Admin** | Cập nhật allowed value cụ thể |
| | DELETE | `/api/metadata/{key}` | **Admin** | Xóa metadata type (chỉ khi không có file nào dùng) |
| | DELETE | `/api/metadata/{key}/values/{value}` | **Admin** | Xóa allowed value (chỉ khi không có file nào dùng) |
 
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
     │                              └── GrpcClient.create_inquiry()
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
| InquiryService | Create(CreateInquiryRequest) | Sau khi soạn xong draft inquiry |
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
MONGODB_DB_NAME=ai_service

# === R2 ===
R2_ENDPOINT=localhost:9000
R2_ACCESS_KEY=r2admin
R2_SECRET_KEY=r2admin
R2_BUCKET_NAME=rag-files
R2_SECURE=false

# === RabbitMQ ===
RABBITMQ_ENABLED=true
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_INGEST_QUEUE=email_ingest_queue

# === gRPC (nest-api) ===
GRPC_URL=localhost:5000   # gRPC AuthService.VerifyToken + InquiryService.Create
GRPC_ENABLED=true
GRPC_TIMEOUT_SECONDS=3.0

# === Upload ===
MAX_FILE_SIZE_MB=20
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


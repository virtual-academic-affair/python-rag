# Email AI Service (python-rag)

**Version 3.0.0** — Microservice hợp nhất giữa **phân loại email tự động** và **tìm kiếm tài liệu dựa trên RAG** cho hệ thống hỗ trợ sinh viên đại học.

---

## Tổng quan

Service nhận email từ sinh viên qua RabbitMQ, tự động phân loại và xử lý:

- **classRegistration** → trích xuất thông tin đăng ký môn học thành JSON cấu trúc
- **inquiry** → soạn email trả lời tự động bằng RAG (tìm trong tài liệu nội bộ)
- **task** → ghi nhận nhiệm vụ hành chính
- **other** → các email không thuộc danh mục trên

Ngoài ra cung cấp API quản lý kho tài liệu (upload, tìm kiếm, chat RAG).

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
python-rag/
├── app/
│   ├── main.py                         # FastAPI app, lifespan, middleware
│   ├── api/
│   │   ├── router.py                   # Tổng hợp tất cả router
│   │   └── endpoints/
│   │       ├── classification.py       # POST /process, /api/test/...
│   │       ├── chat.py                 # POST /api/chat/query|stream
│   │       ├── files.py                # CRUD /api/files
│   │       ├── stores.py               # CRUD /api/stores
│   │       └── metadata.py             # CRUD /api/metadata
│   ├── core/
│   │   ├── config.py                   # Settings từ .env (pydantic-settings)
│   │   ├── database.py                 # MongoDB connection (Motor)
│   │   ├── exceptions.py               # Custom exception hierarchy
│   │   └── prompts.py                  # System prompts cho Gemini
│   ├── dependencies/
│   │   └── auth.py                     # require_auth, require_admin (FastAPI Depends)
│   ├── models/
│   │   ├── database.py                 # MongoDB document models (dataclass)
│   │   ├── enums.py                    # FileStatus enum
│   │   └── schemas.py                  # Pydantic request/response schemas
│   ├── proto/
│   │   ├── auth.proto                  # gRPC AuthService.VerifyToken
│   │   ├── auth_pb2.py                 # Compiled protobuf
│   │   ├── auth_pb2_grpc.py            # AuthServiceStub (client-only)
│   │   ├── inquiry.proto                 # gRPC InquiryService.Create
│   │   ├── inquiry_pb2.py                # Compiled protobuf
│   │   └── inquiry_pb2_grpc.py           # EmailServiceStub (client-only)
│   ├── repositories/
│   │   ├── base.py                     # BaseRepository (CRUD generic)
│   │   ├── file_repository.py
│   │   ├── store_repository.py
│   │   └── metadata_repository.py
│   ├── services/
│   │   ├── auth/
│   │   │   └── grpc_nest_auth.py       # GrpcClient (verify qua gRPC)
│   │   ├── grpc/
│   │   │   └── nest_email_client.py    # GrpcClient (tạo Gmail draft)
│   │   ├── messaging/
│   │   │   ├── rabbitmq_service.py     # RabbitMQ connection
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
│   │       ├── gemini_service.py       # Singleton Gemini client (chat + draft)
│   │       ├── file_service.py         # Upload file → MinIO + Gemini
│   │       ├── store_service.py        # Quản lý Gemini File Search store
│   │       ├── metadata_service.py     # CRUD + validate metadata types
│   │       └── email_draft_service.py  # Hàm thuần soạn email trả lời (RAG)
│   ├── storage/
│   │   └── minio_client.py             # MinIO client singleton
│   └── utils/
│       ├── filter_builder.py           # Build Gemini filter string (role-based)
│       ├── store_utils.py              # Resolve store ID, convert filter
│       ├── file_utils.py               # Validate size, extension, MIME
│       ├── db_utils.py                 # MongoDB helper
│       └── pagination.py               # Paginated response helper
├── scripts/
│   ├── seed_metadata.py                # Seed 3 metadata types hệ thống
│   ├── init_db.py                      # Khởi tạo index MongoDB
│   └── drop_database.py                # Xóa toàn bộ database
├── run.py                              # Entry point (uvicorn)
├── requirements.txt
└── .env                                # Biến môi trường
```

---

## Cài đặt & Chạy

### Yêu cầu

- Python 3.10+
- Docker & Docker Compose
- MongoDB (Atlas free tier hoặc local)
- Google Gemini API Key — [lấy tại đây](https://aistudio.google.com/apikey)

### 1. Tạo môi trường ảo và cài dependencies

```bash
# Tạo môi trường ảo
python3 -m venv .venv

# Kích hoạt môi trường ảo
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate        # Windows

# Cài đặt dependencies
pip install -r requirements.txt
```

### 2. Cấu hình môi trường

Tạo file `.env` (xem phần Environment Variables bên dưới):

```bash
GOOGLE_API_KEY=your_gemini_key
MONGODB_URL=mongodb+srv://...
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

### 3. Khởi động Docker services

`docker-compose.yml` trong thư mục `python-rag/` chứa các services: **MinIO** và **RabbitMQ**.

```bash
# Chỉ khởi động MinIO (nếu RabbitMQ đã được khởi động từ nest-api)
./start.sh

# Khởi động tất cả – MinIO + RabbitMQ
./start.sh --all
```

Dừng services:

```bash
# Dừng app + MinIO
./stop.sh

# Dừng app + MinIO + RabbitMQ
./stop.sh --all
```

### 4. Seed dữ liệu ban đầu

```bash
# Tạo indexes MongoDB
python scripts/init_db.py

# Seed 3 metadata types hệ thống (academic_year, cohort, access_scope)
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
| MinIO Console | http://localhost:9001 (admin/minioadmin) |
| RabbitMQ Management | http://localhost:15672 (guest/guest) |

---

## API Endpoints

### Email Classification
```
POST /process                           Phân loại email thủ công
POST /api/test/classification/ingested  Test phân loại từ message RabbitMQ
```

### Chat (RAG)
```
POST /api/chat/query            Hỏi đáp RAG (trả lời đầy đủ)
POST /api/chat/stream           Hỏi đáp RAG (streaming SSE)
```

### Files
```
POST   /api/files               Upload file vào store
POST   /api/files/batch         Upload nhiều file
GET    /api/files               Danh sách file
GET    /api/files/{id}          Chi tiết file
DELETE /api/files/{id}          Xóa file
DELETE /api/files/bulk          Xóa nhiều file
```

### Stores (Kho tài liệu)
```
POST   /api/stores              Tạo store mới
GET    /api/stores              Danh sách store
GET    /api/stores/{id}         Chi tiết store
PATCH  /api/stores/{id}         Cập nhật store
DELETE /api/stores/{id}         Xóa store
```

### Metadata
```
POST   /api/metadata            Tạo metadata type mới
GET    /api/metadata            Danh sách metadata types
GET    /api/metadata/{key}      Chi tiết metadata type
PATCH  /api/metadata/{key}      Cập nhật metadata type
DELETE /api/metadata/{key}      Xóa metadata type (không được xóa system types)
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
     ├─[classRegistration]─▶ ClassRegistrationService → trích xuất JSON
     │
     ├─[inquiry]───────────▶ InquiryService.process()
     │                              ├── draft_inquiry_email_reply() (RAG)
     │                              │       └── GeminiService.draft_email_reply()
     │                              │                └── Gemini File Search store
     │                              └── GrpcClient.create_draft()
     │                                      └── nest-api InquiryService.Create (gRPC)
     │
     ├─[task]──────────────▶ TaskService (log)
     │
     └─[other]─────────────▶ OtherService (log)
          │
          ▼
     Kết quả trả về NestJS qua RabbitMQ reply
```

---

## Hệ thống Metadata

Metadata được dùng để tag file khi upload và filter khi tìm kiếm RAG.

**3 system metadata types (không thể xóa):**

| Key | Mô tả | Ví dụ giá trị |
|---|---|---|
| `academic_year` | Năm học | 2023-2024, 2024-2025 |
| `cohort` | Khóa sinh viên | K62, K63, K64, K65, K66, K67 |
| `access_scope` | Phạm vi truy cập | `cong_khai`, `noi_bo` |

**Quy tắc validate khi upload file:**
- `access_scope` bắt buộc
- Phải có ít nhất `academic_year` HOẶC `cohort`
- Giá trị phải nằm trong `allowed_values` đang active

**Phân quyền filter RAG:**
- `student` → tự động giới hạn `access_scope = "cong_khai"`
- `staff` / `admin` → không giới hạn access_scope

---

## Environment Variables

```env
# === AI ===
GOOGLE_API_KEY=           # Gemini API key (bắt buộc)
LLM_MODEL=gemini-2.5-flash      # Model cho classification
GEMINI_MODEL=gemini-2.5-flash   # Model cho RAG chat/draft

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
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_INGEST_QUEUE=email.ingest

# === gRPC (nest-api) ===
GRPC_URL=localhost:5000   # gRPC AuthService.VerifyToken + InquiryService.Create
                                # nest-api cần chạy với START_GRPC=true

# === Upload ===
MAX_FILE_SIZE_MB=50
ALLOWED_EXTENSIONS=pdf,docx,doc,txt,md,html
```

---

## Giao tiếp với nest-api

### Chiều nhận (RabbitMQ)

nest-api gửi email đến python-rag qua RabbitMQ queue `email.ingest`:

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

### Chiều gửi (gRPC) — python-rag → nest-api

python-rag gọi nest-api qua gRPC dùng pool connection duy nhất với `grpc.aio`.
Các endpoints hỗ trợ:
- InquiryService.Create(messageId, answer, question, types, sources)
- AuthService.VerifyToken()
- MessageService.UpdateLabels()
- Tasks/ClassReg

Client hợp nhất: `app/services/integrations/grpc_client.py`.

---

## Scripts

```bash
# Tạo indexes MongoDB
python scripts/init_db.py

# Seed metadata types hệ thống
python scripts/seed_metadata.py

# Xóa toàn bộ database (cẩn thận!)
python scripts/drop_database.py
```

---

## License

[Add your license here]

Email AI Service is a production-ready FastAPI microservice that provides:

### **Email Classification & Extraction**
- Automatic email classification into 4 categories:
  - `classRegistration`: Course registration/cancellation requests
  - `task`: Administrative tasks from departments
  - `inquiry`: Student questions (auto-drafted with RAG)
  - `other`: Miscellaneous emails
- Structured data extraction for class registration emails
- RabbitMQ integration for async processing

### **RAG-Based Features**
- **Document Management**: Upload PDF, DOCX, DOC, TXT, MD, HTML files
- **Vector Search**: Powered by Gemini File Search API
- **Chat API**: Answer questions using document knowledge base
- **Auto Email Draft**: Generate professional email replies for inquiry labels
- **Metadata System**: Custom metadata with validation and filtering
- **Multi-Store Support**: Organize documents by department/topic

## 🏗️ Architecture

```
NestJS Backend
     │
     ▼ (RabbitMQ)
Email Ingest Consumer
     │
     ├──▶ Classify Email (Gemini)
     │
     ├──▶ classRegistration → Extract structured data
     ├──▶ inquiry → Draft email reply (RAG)
     ├──▶ task → Log
     └──▶ other → Log
```

## 📦 Tech Stack

- **Framework**: FastAPI 0.125.0
- **AI/LLM**: Google Gemini (google-genai 1.56.0)
- **Database**: MongoDB (Motor 3.3.2)
- **Storage**: MinIO 7.2.3 (S3-compatible)
- **Messaging**: RabbitMQ (pika 1.3.2)
## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Docker & Docker Compose
- MongoDB Atlas account (free tier)
- Google Gemini API Key ([Get it here](https://aistudio.google.com/apikey))

### Installation

1. **Clone and setup**
```bash
git clone <repo-url>
cd python-rag
cp .env.example .env
```

2. **Configure environment variables**
Edit `.env` file:
```bash
# Required
GOOGLE_API_KEY=your_key_here
MONGODB_URL=mongodb+srv://...
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

3. **Start all services**
```bash
./start.sh
```

This will:
- Start MinIO (port 9000, 9001)
- Start RabbitMQ (port 5672, 15672)
- Install Python dependencies
- Start FastAPI app (port 8000)

### Access Points

- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **MinIO Console**: http://localhost:9001 (admin/minioadmin)
- **RabbitMQ Management**: http://localhost:15672 (guest/guest)

## 📚 API Endpoints

### Email Classification
```
POST /api/classification/classify       # Classify email only
POST /api/classification/extract        # Classify + extract data
```

### RAG Features  
```
POST /api/chat/query                    # RAG-based chat
POST /api/chat/stream                   # Streaming chat (SSE)
```

### File Management
```
POST   /api/files                       # Upload file
POST   /api/files/batch                 # Batch upload
GET    /api/files                       # List files
GET    /api/files/{id}                  # Get file details
DELETE /api/files/{id}                  # Delete file
```

### Store Management
```
POST   /api/stores                      # Create knowledge base
GET    /api/stores                      # List stores
GET    /api/stores/{id}                 # Get store details
DELETE /api/stores/{id}                 # Delete store
```

### Metadata Management
```
POST   /api/metadata                    # Create metadata type
GET    /api/metadata                    # List metadata types
GET    /api/metadata/{id}               # Get metadata type
PATCH  /api/metadata/{id}               # Update metadata type
DELETE /api/metadata/{id}               # Delete metadata type
```

## 🔄 Email Processing Flow

### Inquiry Email (with Auto-Draft)
```json
// 1. RabbitMQ Input
{
  "emailId": 12345,
  "subject": "Hỏi về lịch thi",
  "senderEmail": "student@example.com",
  "senderName":  "Nguyen Van A",
  "content": "Em muốn biết lịch thi học kỳ này..."
}

// 2. Classification → inquiry

//3. Auto-drafted email reply using RAG

// 4. Response to NestJS
{
  "internal": {"mail_id": "12345", "id_record": "12345"},
  "label": "inquiry",
  "question": "Lịch thi tổ chức khi nào?",
      "types": ["procedure"],
  "answer": "Kính gửi bạn Nguyen Van A,\n\n...",
  "tone": "formal-friendly",
  "sources": [...]
}
```

## 🛠️ Development

### Run tests
```bash
pytest tests/
```

### Stop services
```bash
./stop.sh
```

### Database scripts
```bash
# Initialize database with seed data
python scripts/init_db.py

# Seed system metadata
python scripts/seed_metadata.py

# Drop database
python scripts/drop_database.py
```

## 📖 Documentation

- [API Documentation](docs/API.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Migration Guide](docs/MIGRATION.md)

## 🔐 Environment Variables

See [.env.example](.env.example) for all available configuration options.

Required variables:
- `GOOGLE_API_KEY`: Gemini API key
- `MONGODB_URL`: MongoDB connection string
- `MINIO_ACCESS_KEY`: MinIO access key
- `MINIO_SECRET_KEY`: MinIO secret key

## 📝 License

[Add your license here]

## 🤝 Contributing

[Add contributing guidelines]

---

**Version History:**
- v3.0.0: Unified service (classification + RAG)
- v2.x: RAG Service
- v1.x: Classification Service
HOST=0.0.0.0
PORT=8000
RELOAD=true
UVICORN_LOG_LEVEL=info

# Optional - Application Logging
LOG_LEVEL=INFO

# Optional - RabbitMQ Configuration
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_VHOST=/
```

4. Run the service:
```bash
python run.py
```

Or:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The service will be available at `http://localhost:8000`

## API Documentation

Once running, visit:
- API docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Endpoints

### POST /process

Classifies email and extracts structured information from title and content.

**Request Body:**
```json
{
    "internal": {
        "mail_id": "bhdn2ldnnx",
        "id_record": "12n#a2@@"
    },
    "title": "Đăng ký lớp học phần - Nhập môn lập trình",
    "content": "Kính gửi phòng đào tạo,\n\nTôi là sinh viên Nguyễn Văn A, mã sinh viên: 22127259, lớp: 22CLC01, khóa 2022.\n\nTôi muốn đăng ký lớp học phần:\n- Môn học: Nhập môn lập trình (CSC101)\n- Mã lớp: CNPM01\n- Thứ: Thứ 2 (Monday)\n- Thời gian: 07:30:00\n\nXin cảm ơn!"
}
```

**Response for class_registration (đăng ký):**
```json
{
    "internal": {
        "mail_id": "bhdn2ldnnx",
        "id_record": "12n#a2@@"
    },
    "types": ["class_registration"],
    "student": {
        "code": "22127259",
        "name": "Nguyen Van A",
        "class": "22CLC01",
        "year": 2022
    },
    "class": [
        {
            "code": "CNPM01",
            "day": "MON",
            "time": "07:30:00",
            "action": "join"
        }
    ],
    "course": {
        "code": "CSC101",
        "name": "Nhập môn lập trình"
    }
}
```

**Response for class_registration (đổi lớp):**
```json
{
    "internal": {
        "mail_id": "bhdn2ldnnx",
        "id_record": "12n#a2@@"
    },
    "types": ["class_registration"],
    "student": {
        "code": "22127259",
        "name": "Nguyen Van A",
        "class": "22CLC01",
        "year": 2022
    },
    "class": [
        {
            "code": "OLD01",
            "day": "MON",
            "time": "07:30:00",
            "action": "cancel"
        },
        {
            "code": "NEW01",
            "day": "TUE",
            "time": "09:00:00",
            "action": "join"
        }
    ],
    "course": {
        "code": "CSC101",
        "name": "Nhập môn lập trình"
    }
}
```

**Response for other types:**
```json
{
    "internal": {
        "mail_id": "bhdn2ldnnx",
        "id_record": "12n#a2@@"
    },
    "types": ["administrative"]
}
```

## Sample cURL Requests

### Class Registration Request
```bash
curl -X POST "http://localhost:8000/process" \
  -H "Content-Type: application/json" \
  -d '{
    "internal": {
      "mail_id": "bhdn2ldnnx",
      "id_record": "12n#a2@@"
    },
    "title": "Đăng ký lớp học phần - Nhập môn lập trình",
    "content": "Kính gửi phòng đào tạo,\n\nTôi là sinh viên Nguyễn Văn A, mã sinh viên: 22127259, lớp: 22CLC01, khóa 2022.\n\nTôi muốn đăng ký lớp học phần:\n- Môn học: Nhập môn lập trình (CSC101)\n- Mã lớp: CNPM01\n- Thứ: Thứ 2 (Monday)\n- Thời gian: 07:30:00\n\nXin cảm ơn!"
  }'
```

### Administrative Request
```bash
curl -X POST "http://localhost:8000/process" \
  -H "Content-Type: application/json" \
  -d '{
    "internal": {
      "mail_id": "email_789",
      "id_record": "record_101"
    },
    "title": "Yêu cầu cấp bản sao bảng điểm",
    "content": "Kính gửi phòng đào tạo,\n\nTôi là sinh viên Jane Smith, mã sinh viên: ST2022001.\n\nTôi cần bản sao bảng điểm để nộp hồ sơ xin việc. Xin vui lòng hỗ trợ.\n\nCảm ơn!"
  }'
```

### Graduation Request
```bash
curl -X POST "http://localhost:8000/process" \
  -H "Content-Type: application/json" \
  -d '{
    "internal": {
      "mail_id": "email_456",
      "id_record": "record_789"
    },
    "title": "Đăng ký bảo vệ khóa luận tốt nghiệp",
    "content": "Kính gửi phòng đào tạo,\n\nTôi là sinh viên Mike Johnson, mã sinh viên: ST2020001, sinh viên năm cuối ngành Khoa học Máy tính.\n\nTôi muốn đăng ký lịch bảo vệ khóa luận tốt nghiệp. Xin vui lòng sắp xếp lịch phù hợp.\n\nCảm ơn!"
  }'
```

## Response Format

The service returns data directly (not wrapped in `success`/`data` structure):

- **internal**: Contains `mail_id` and `id_record` (returned exactly as received)
- **types**: Array of classification types (e.g., `["class_registration"]`)
- **student**: Student information (code, name, class, year) - only for class_registration
- **class**: Array of class information objects, each with:
  - `code`: Class code
  - `day`: Day of week (MON, TUE, WED, etc.)
  - `time`: Class start time (HH:MM:SS)
  - `action`: "join" (đăng ký) or "cancel" (hủy)
  - Only for class_registration, can contain 1-2 objects (2 for class change)
- **course**: Course information (code, name) - only for class_registration

## Classification Categories

- **class_registration**: Đăng ký lớp học phần, hủy lớp, đổi lớp
- **administrative**: Đơn từ, thủ tục hành chính, cấp bản sao, giấy tờ
- **graduation**: Tốt nghiệp, bảo vệ khóa luận, đồ án
- **academic_programme**: Học vụ, vấn đề học tập, chương trình học, môn học, giảng viên
- **department**: Công việc từ các phòng khác (PDT, PKT gửi bảng điểm, đơn phúc khảo)
- **other**: Khác

## Environment Variables

### Required
- `GOOGLE_API_KEY`: Your Google API key for Gemini access

### Optional - LangChain/LLM Configuration
- `LLM_MODEL`: Model name to use (default: `gemini-2.5-flash-lite`)
  - Available models: `gemini-2.5-flash-lite`, `gemini-1.5-pro`, `gemini-1.5-flash`, `gemini-pro`, etc.
- `LLM_TEMPERATURE`: Temperature for model responses, controls randomness (default: `0.1`)
  - Range: 0.0 to 2.0
  - Lower values = more deterministic, Higher values = more creative

### Optional - Server Configuration
- `HOST`: Server host (default: `0.0.0.0`)
- `PORT`: Server port (default: `8000`)
- `RELOAD`: Enable auto-reload on code changes (default: `true`)
- `UVICORN_LOG_LEVEL`: Uvicorn log level - `critical`, `error`, `warning`, `info`, `debug`, `trace` (default: `info`)

### Optional - Application Logging
- `LOG_LEVEL`: Application log level - `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (default: `INFO`)

## Testing

### Using Postman
Import the Postman collection: `Email_Langchain_API.postman_collection.json`

### Using cURL
See `CURL_EXAMPLES.md` for detailed cURL examples.

### Quick Test
```bash
curl -X POST "http://localhost:8000/process" \
  -H "Content-Type: application/json" \
  -d '{
    "internal": {
      "mail_id": "test123",
      "id_record": "record456"
    },
    "title": "Đăng ký lớp học phần",
    "content": "Tôi muốn đăng ký lớp học phần..."
  }'
```

Make sure the server is running before executing tests.

## Error Handling

The service includes comprehensive error handling:
- Invalid JSON responses from AI are handled gracefully
- Missing environment variables are caught at startup
- All errors are logged with appropriate detail levels
- HTTP exceptions return structured error responses

## Logging

The service logs:
- Request processing start/completion
- Classification results
- Extraction successes/failures
- Error details for debugging

## RabbitMQ Integration

This service uses RabbitMQ for token management and message queuing.

### Features
- **Token Storage**: Tokens are stored in RabbitMQ with in-memory caching
- **Message Queue**: Supports async message processing
- **Persistence**: All messages are persisted in RabbitMQ
- **Reliability**: Ensures message delivery with acknowledgment

### Configuration
See [RABBITMQ_SETUP.md](RABBITMQ_SETUP.md) for detailed setup instructions.

### Testing RabbitMQ
```bash
python test_rabbitmq.py
```

### RabbitMQ Management Console
Access at: `http://localhost:15672`
- Username: guest
- Password: guest

## Migration from Redis

If you're upgrading from a previous version that used Redis, see [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) for detailed migration instructions.

## Documentation

- [RABBITMQ_SETUP.md](RABBITMQ_SETUP.md) - RabbitMQ installation and configuration
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) - Migration guide from Redis to RabbitMQ
- [CHANGES_SUMMARY.md](CHANGES_SUMMARY.md) - Summary of all changes

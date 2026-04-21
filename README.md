# AI Service - Unified Modular RAG & Email Classification

**Version 4.6.0** — Microservice hợp nhất giữa **phân loại email tự động** và **tìm kiếm tài liệu thông minh (Modular RAG)** phục vụ hệ thống quản lý học thuật đại học.

---

## 🚀 Tổng quan

Dự án này là trái tim xử lý AI của hệ thống, thực hiện hai nhiệm vụ cốt lõi:

1.  **Phân loại & Xử lý Email**: Nhận thông tin từ RabbitMQ, tự động nhận diện ý định (Classification) và trích xuất dữ liệu (Extraction) để gọi các workflows gRPC (ClassRegistration, Task, Inquiry).
2.  **Modular RAG Ecosystem**: Hệ thống tìm kiếm và hỏi đáp tài liệu không phụ thuộc vào Gemini File Search, sử dụng pipeline mạnh mẽ:
    *   **LlamaParse**: Bọc tách tài liệu PDF phức tạp sang Markdown chuẩn.
    *   **PageIndex**: Đánh chỉ mục cấu trúc (TOC), quản lý phân đoạn văn bản phân cấp và **Agentic Tools**.
    *   **Qdrant**: Vector Database lưu trữ embeddings phục vụ tìm kiếm ngữ nghĩa.
    *   **Real-time Progress**: Theo dõi tiến trình nạp liệu thời gian thực qua WebSockets.
    *   **Semantic Scoring**: Sử dụng thuật toán **DocScore (PageIndex Formula)** để xếp hạng tài liệu dựa trên phân nhóm chunks và cấu trúc mục lục.

---

## 🛠 Tech Stack

| Thành phần | Công nghệ | Lưu ý |
|---|---|---|
| **Web Framework** | FastAPI | Async/Await, Pydantic v2 |
| **AI Processing** | Google Gemini (2.5-flash / Pro) | Xử lý ngôn ngữ tự nhiên & Reasoning |
| **Parsing & Chunking** | LlamaIndex / LlamaParse | Chuyển đổi PDF và băm nhỏ văn bản |
| **Indexing Structure** | PageIndex | Lưu trữ cấu trúc mục lục tài liệu (Hierarchy) |
| **Vector Database** | Qdrant | Công cụ tìm kiếm vector mật độ cao |
| **Metadata Database** | MongoDB (Motor client) | Quản lý tệp, metadata và logging |
| **Object Storage** | Cloudflare R2 | Lưu trữ binary file và markdown |
| **Message Broker** | RabbitMQ | Nhận tin nhắn từ NestJS backend |
| **Internal RPC** | gRPC | Giao thức truyền tin hiệu năng cao với nest-api |

---

## 📂 Cấu trúc dự án (Refactored)

```text
python-rag/
├── app/
│   ├── api/                    # Cổng vào API tổng hợp (router.py)
│   ├── core/                   # Cấu hình lõi (Database, Exceptions, Converters)
│   ├── integrations/           # Client wrappers (R2, Qdrant, PageIndex, gRPC)
│   ├── modules/                # Business Logic phân mảnh theo Domain
│   │   ├── chat/               # Agentic Chat RAG & Streaming
│   │   ├── email/              # Orchestrator & Workflow classification
│   │   ├── files/              # Quản lý tệp (Upload, Delete, TOC Tree)
│   │   ├── metadata/           # Quản lý nhãn và Role-based masking
│   │   └── retrieval/          # Retrieval Service & Tool-use logic
│   ├── pipelines/              # Quy trình xử lý phức tạp (Ingestion)
│   ├── proto/                  # Protobuf definitions & generated stubs
│   └── repositories/           # Tầng truy cập dữ liệu MongoDB (Base Pattern)
├── docs/                       # Tài liệu chi tiết hệ thống (api.txt, overview)
├── scripts/                    # Công cụ quản trị, Test & Seed dữ liệu
├── Dockerfile                  # Cấu hình containerization
└── requirements.txt            # Danh mục thư viện Python
```

---

## ⚙️ Cài đặt & Khởi chạy

### 1. Chuẩn bị môi trường
Yêu cầu Python 3.10+, Docker (cho Qdrant/RabbitMQ).

```bash
python -m venv .venv
source .venv/bin/activate  # Hoặc .venv\Scripts\activate trên Windows
pip install -r requirements.txt
```

### 2. Cấu hình .env
Sao chép `.env.example` thành `.env` và điền các tham số:
*   `GOOGLE_API_KEY`: Lấy từ Google AI Studio.
*   `QDRANT_URL`: Địa chỉ Vector DB.
*   `MONGODB_URL`: Kết nối MongoDB.
*   `PAGEINDEX_WORKSPACE`: Đường dẫn thư mục lưu cache indexing PageIndex.

### 3. Khởi tạo dữ liệu
Đây là bước bắt buộc trước khi chạy hệ thống lần đầu:

```bash
# Xóa và tạo mới Database/Vector/R2
python scripts/init_db.py --skip-confirm

# Seed các nhãn metadata hệ thống (academic_year, cohort, access_scope)
python scripts/seed_metadata.py
```

### 4. Chạy Service
```bash
python run.py
```

---

## 📖 Tài liệu hướng dẫn

Hệ thống có bộ tài liệu cực kỳ chi tiết tại thư mục `docs/`:

*   👉 **[Đặc tả API (docs/api.txt)](file:///Users/trangvu/Documents/Phuc/giao_vu/email/refactor/python-rag/docs/api.txt)**: Danh sách đầy đủ 25 endpoints kèm Workflow, Request/Response mẫu (Chuẩn CamelCase).
*   👉 **[Kiến trúc hệ thống (docs/project-overview.txt)](file:///Users/trangvu/Documents/Phuc/giao_vu/email/refactor/python-rag/docs/project-overview.txt)**: Mô tả chuyên sâu về pipeline nạp liệu, logic Agentic RAG và cơ chế xác thực gRPC.

---

## 🔐 Bảo mật & Phân quyền

Hệ thống sử dụng gRPC để xác thực JWT Token từ NestJS. Các mức truy cập:
*   **Public**: Health check.
*   **Student**: Truy vấn chat RAG & xem tệp mang chính xác nhãn `student`.
*   **Lecture**: Truy vấn chat RAG & xem tệp mang chính xác nhãn `lecture`. (Không thấy tệp của Student trừ khi tệp đó được gán cả 2 nhãn).
*   **ADMIN**: Quản lý toàn bộ hệ thống, xem được mọi tệp kể cả tệp nội bộ (Empty/Internal scope).

**Cơ chế Masking**: Một số giá trị nhãn Metadata (như "Phòng ban nội bộ") sẽ tự động bị ẩn đối với vai trò `student` dựa trên cấu hình `visibleRoles` trong Metadata Type.

---

## 🛠 Bảo trì & Kiểm thử

Để kiểm tra toàn bộ luồng RAG từ lúc nạp tệp đến lúc chat:
```bash
python scripts/test_upload_n_chat.py
```

Kết quả sẽ được lưu vào thư mục `scripts/test_results/`.

---
*© 2026 AI Service Team - Google DeepMind Built.*

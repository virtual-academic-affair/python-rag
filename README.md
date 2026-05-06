# AI Service - Unified Modular RAG & Email Classification

**Version 5.3.0** — Microservice hợp nhất giữa **phân loại email tự động** và **tìm kiếm tài liệu thông minh (Modular RAG)** phục vụ hệ thống quản lý học thuật đại học.

---

## 🚀 Tổng quan

Dự án này là trái tim xử lý AI của hệ thống, thực hiện hai nhiệm vụ cốt lõi: 

1.  **Phân loại & Xử lý Email**: Nhận thông tin từ RabbitMQ, tự động nhận diện ý định (Classification) và trích xuất dữ liệu (Extraction) để gọi các workflows gRPC (ClassRegistration, Task, Inquiry).
2.  **Modular RAG Ecosystem**: Hệ thống Modular RAG độc lập, lưu trữ dữ liệu tại chỗ (State-free), sử dụng pipeline mạnh mẽ:
    *   **LlamaParse**: Bọc tách tài liệu PDF phức tạp sang Markdown chuẩn.
    *   **PageIndex**: Đánh chỉ mục cấu trúc (TOC), quản lý phân đoạn văn bản phân cấp và **Agentic Tools**.
    *   **Qdrant**: Vector Database lưu trữ embeddings phục vụ tìm kiếm ngữ nghĩa.
    *   **Real-time Progress**: Theo dõi tiến trình nạp liệu thời gian thực qua WebSockets (`/api/files/progress/{clientId}`).
    *   **Semantic Scoring**: Sử dụng thuật toán **DocScore (PageIndex Formula)** để xếp hạng tài liệu dựa trên phân nhóm chunks và cấu trúc mục lục.
    *   **Tiêu chuẩn Ingestion Flow**: Upload -> R2 -> LlamaParse -> PageIndex (TOC) -> Qdrant (Chunks/Embeddings).
3.  **Semantic FAQ Module (v2)**: Hệ thống quản lý câu hỏi thường gặp thông minh:
    *   **Hybrid Search**: Kết hợp **Semantic Match** (Gemini Embeddings) và **Native MongoDB Full-Text Search (FTS)** trên các trường không dấu (`unaccented`), đảm bảo tìm kiếm chính xác cả từ khóa thô và ý nghĩa ngữ nghĩa.
    *   **Auto-Synthesis**: Tự động gom cụm các tương tác người dùng (Clustering) và sử dụng LLM để tổng hợp FAQ mới từ dữ liệu thực tế.
    *   **Bulk Import & Management**: Hỗ trợ nạp hàng loạt FAQ từ Excel (.xlsx) hoặc JSON với hiệu suất cao (parallel embeddings).
    *   **[NEW] Formatting Preservation**: Tự động giữ nguyên định dạng Rich Text (Bold, Italic, Underline) và Hyperlinks từ file Excel, chuyển đổi sang Markdown để hiển thị đồng nhất.
    *   **Interaction Logging**: Theo dõi lịch sử chat/email để phục vụ cải tiến hệ thống và tổng hợp kiến thức.
4.  **Hardened Metadata Architecture**:
    *   **Rigid Schema**: Chuyển đổi từ tag mảng sang cấu trúc đối tượng `YearRange` (`fromYear`, `toYear`) nghiêm ngặt.
    *   **Unified Schema Endpoint**: Truy cập `/api/metadata/schema` để lấy định nghĩa cấu trúc metadata chuẩn cho toàn hệ thống.
    *   **Range Search**: Hỗ trợ tìm kiếm tài liệu theo khoảng năm giao thoa (overlap) chính xác.
5.  **Forms Management Module**: Quản lý các liên kết biểu mẫu và quy trình học thuật:
    *   **Unified Content**: Gộp tên hiển thị và đường dẫn vào một trường Rich Text duy nhất, hỗ trợ định dạng linh hoạt.
    *   **Link Optimization**: Tự động xử lý mọi liên kết trong Rich Text để mở trong tab mới (`target="_blank"`), đảm bảo trải nghiệm người dùng không bị gián đoạn.
    *   **Bulk Import**: Nạp hàng loạt biểu mẫu từ Excel với cơ chế chuẩn hóa số liệu (ví dụ: `2020.0` -> `2020`) và bảo toàn định dạng Rich Text.

---

## 🛠 Tech Stack

| Thành phần | Công nghệ | Lưu ý |
|---|---|---|
| **Web Framework** | FastAPI | Async/Await, Pydantic v2 |
| **AI Processing** | Google Gemini (2.5-flash / Pro) | Xử lý ngôn ngữ tự nhiên & Reasoning |
| **Parsing & Chunking** | LlamaParse              | Chuyển đổi PDF và băm nhỏ văn bản |
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
│   ├── integrations/           # Client wrappers (R2, Qdrant, PageIndex, gRPC, Excel)
│   ├── modules/                # Business Logic phân mảnh theo Domain
│   │   ├── chat/               # Agentic Chat RAG & Streaming
│   │   ├── email/              # Orchestrator & Workflow classification
│   │   ├── faq/                # [NEW] Quản lý FAQ, Semantic Search & Synthesis
│   │   ├── forms/              # [NEW] Quản lý biểu mẫu và liên kết học thuật
│   │   ├── files/              # Quản lý tệp (Upload, Delete, TOC Tree)
│   │   ├── metadata/           # Quản lý nhãn và Validation
│   │   └── rag/                # RAG Service & Tool-use logic
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
# Xóa và tạo mới Database/Vector/R2, sau đó tự động nạp FAQ mẫu
python scripts/init_db.py --skip-confirm

# Metadata system initialization
# seed_metadata.py logic merged into init_db.py

# [Optional] Seed dữ liệu FAQ mẫu thủ công từ file JSON khác
python scripts/seed_faqs.py --file scripts/sample_faqs.json
```

### 4. Chạy Service
```bash
python run.py
```

---

## 📖 Tài liệu hướng dẫn

Hệ thống có bộ tài liệu cực kỳ chi tiết tại thư mục `docs/`:

*   👉 **[Đặc tả API (docs/api.txt)]**: Danh sách đầy đủ các endpoints kèm Workflow, Request/Response mẫu (Chuẩn CamelCase).
*   👉 **[Kiến trúc hệ thống (docs/project-overview.txt)]**: Mô tả chuyên sâu về pipeline nạp liệu, logic Agentic RAG và cơ chế xác thực gRPC.

---

## 🔐 Bảo mật & Phân quyền

Hệ thống sử dụng gRPC để xác thực JWT Token từ NestJS. Mọi người dùng hợp lệ đều có quyền truy vấn kho tài liệu chung. Quyền quản trị (ADMIN) được yêu cầu cho các tác vụ thay đổi cấu hình hệ thống và Metadata Types.

---

## 🛠 Bảo trì & Kiểm thử

Để kiểm tra toàn bộ luồng RAG từ lúc nạp tệp đến lúc chat:
```bash
python scripts/test_upload_n_chat.py
```

Kết quả sẽ được lưu vào thư mục `scripts/test_results/`.

---
*© 2026 AI Service Team - Google DeepMind Built.*

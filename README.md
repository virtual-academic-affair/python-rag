# Student Classification Service

A FastAPI service that classifies student and class data using LangChain with Google Gemini AI.

## Project Structure

```
email_langchain/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI application entry point
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py                    # API route definitions
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py                   # Pydantic models and schemas
│   └── services/
│       ├── __init__.py
│       ├── langchain_service.py         # Main LangChain classifier and router
│       ├── class_registration_service.py # Class registration service
│       ├── administrative_service.py     # Administrative requests service
│       ├── graduation_service.py         # Graduation requests service
│       ├── academic_programme_service.py # Academic programme service
│       ├── department_service.py         # Department requests service
│       └── other_service.py             # Other requests service
├── config/
│   ├── __init__.py
│   └── settings.py                      # Application settings
├── .env.example                         # Environment variables template
├── .gitignore                           # Git ignore rules
├── requirements.txt                     # Python dependencies
├── run.py                               # Application runner script
├── README.md                            # Project documentation
├── CURL_EXAMPLES.md                     # cURL examples for testing
└── Email_Langchain_API.postman_collection.json  # Postman collection
```

## Features

- **Multi-category Classification**: Classifies student emails into 6 categories:
  - `class_registration`: Đăng ký/hủy/đổi lớp học phần
  - `administrative`: Đơn từ, thủ tục hành chính
  - `graduation`: Tốt nghiệp
  - `academic_programme`: Học vụ (vấn đề học tập, chương trình, môn học, giảng viên)
  - `department`: Công việc từ các phòng khác (PDT, PKT)
  - `other`: Khác

- **Structured Data Extraction**: Extracts detailed information for class registration:
  - Student information (code, name, class, year)
  - Class information (code, day, time, action: join/cancel)
  - Course information (code, name)
  - Supports class change (returns 2 class objects: cancel old + join new)

- **Service-based Architecture**: Each request type has its own dedicated service for better maintainability

- **Built with FastAPI, LangChain, and Google Gemini**

- **Comprehensive logging and error handling**

- **Pydantic models for request/response validation**

- **Clean and organized folder structure**

## Setup

### Prerequisites
- Python 3.8+
- RabbitMQ server running (see [RABBITMQ_SETUP.md](RABBITMQ_SETUP.md))

### Installation Steps

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up RabbitMQ:
See [RABBITMQ_SETUP.md](RABBITMQ_SETUP.md) for detailed instructions on installing and configuring RabbitMQ.

Quick start with Docker:
```bash
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=guest \
  -e RABBITMQ_DEFAULT_PASS=guest \
  rabbitmq:3-management
```

3. Set up environment variables:
Create a `.env` file in the root directory (you can copy from `.env.example`):
```bash
# Required
GOOGLE_API_KEY=your_google_api_key_here
JWT_SECRET_KEY=your_jwt_secret_key_here

# Optional - LangChain/LLM Configuration
LLM_MODEL=gemini-2.5-flash-lite
LLM_TEMPERATURE=0.1

# Optional - Server Configuration
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

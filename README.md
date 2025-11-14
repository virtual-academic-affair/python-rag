# Student Classification Service

A FastAPI service that classifies student and class data using LangChain with Google Gemini AI.

## Project Structure

```
email_langchain/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py        # API route definitions
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py       # Pydantic models and schemas
│   └── services/
│       ├── __init__.py
│       └── langchain_service.py  # LangChain classification service
├── tests/
│   ├── __init__.py
│   └── test_examples.py     # Test examples
├── config/
│   ├── __init__.py
│   └── settings.py          # Application settings
├── requirements.txt
└── README.md
```

## Features

- Classifies student requests into predefined categories
- Extracts structured data for class registration requests
- Built with FastAPI, LangChain, and Google Gemini
- Comprehensive logging and error handling
- Pydantic models for request/response validation
- Clean and organized folder structure

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables:
Create a `.env` file in the root directory:
```bash
GOOGLE_API_KEY=your_google_api_key_here
```

3. Run the service:
```bash
python -m app.main
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

**Response for class_registration:**
```json
{
    "success": true,
    "data": {
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
        "class": {
            "code": "CNPM01",
            "day": "MON",
            "time": "07:30:00"
        },
        "course": {
            "code": "CSC101",
            "name": "Nhập môn lập trình"
        }
    }
}
```

**Response for other types:**
```json
{
    "success": true,
    "data": {
        "internal": {
            "mail_id": "bhdn2ldnnx",
            "id_record": "12n#a2@@"
        },
        "types": ["administrative_requests"]
    }
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

The service returns data in the following structure:

- **internal**: Contains `mail_id` and `id_record` (returned exactly as received)
- **types**: Array of classification types (e.g., `["class_registration"]`)
- **student**: Student information (code, name, class, year)
- **class**: Class information (code, day, time)
- **course**: Course information (code, name) - only for class_registration type

## Classification Categories

- **class_registration**: Course enrollment, class registration
- **administrative_requests**: Document requests, general admin matters
- **graduation**: Thesis, final projects, graduation ceremonies
- **academic_affairs**: Grades, transcripts, academic policies
- **other**: Anything that doesn't fit above categories

## Environment Variables

- `GOOGLE_API_KEY`: Your Google API key for Gemini access

## Testing

Run the test examples:
```bash
python tests/test_examples.py
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

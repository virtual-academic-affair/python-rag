"""
Test examples for the Student Classification Service
Run this after starting the FastAPI server to test the endpoints
"""

import requests
import json

BASE_URL = "http://localhost:8000"


def test_class_registration():
    """Test class registration classification and extraction"""
    data = {
        "internal": {
            "mail_id": "bhdn2ldnnx",
            "id_record": "12n#a2@@"
        },
        "title": "Đăng ký lớp học phần - Nhập môn lập trình",
        "content": "Kính gửi phòng đào tạo,\n\nTôi là sinh viên Nguyễn Văn A, mã sinh viên: 22127259, lớp: 22CLC01, khóa 2022.\n\nTôi muốn đăng ký lớp học phần:\n- Môn học: Nhập môn lập trình (CSC101)\n- Mã lớp: CNPM01\n- Thứ: Thứ 2 (Monday)\n- Thời gian: 07:30:00\n\nXin cảm ơn!"
    }
    
    response = requests.post(f"{BASE_URL}/process", json=data)
    print("Class Registration Test:")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print("-" * 50)


def test_administrative_request():
    """Test administrative request classification"""
    data = {
        "internal": {
            "mail_id": "email_789",
            "id_record": "record_101"
        },
        "title": "Yêu cầu cấp bản sao bảng điểm",
        "content": "Kính gửi phòng đào tạo,\n\nTôi là sinh viên Jane Smith, mã sinh viên: ST2022001.\n\nTôi cần bản sao bảng điểm để nộp hồ sơ xin việc. Xin vui lòng hỗ trợ.\n\nCảm ơn!"
    }
    
    response = requests.post(f"{BASE_URL}/process", json=data)
    print("Administrative Request Test:")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print("-" * 50)


def test_graduation_request():
    """Test graduation request classification"""
    data = {
        "internal": {
            "mail_id": "email_456",
            "id_record": "record_789"
        },
        "title": "Đăng ký bảo vệ khóa luận tốt nghiệp",
        "content": "Kính gửi phòng đào tạo,\n\nTôi là sinh viên Mike Johnson, mã sinh viên: ST2020001, sinh viên năm cuối ngành Khoa học Máy tính.\n\nTôi muốn đăng ký lịch bảo vệ khóa luận tốt nghiệp. Xin vui lòng sắp xếp lịch phù hợp.\n\nCảm ơn!"
    }
    
    response = requests.post(f"{BASE_URL}/process", json=data)
    print("Graduation Request Test:")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print("-" * 50)


def test_health_check():
    """Test health check endpoint"""
    response = requests.get(f"{BASE_URL}/health")
    print("Health Check Test:")
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    print("-" * 50)


if __name__ == "__main__":
    print("Testing Student Classification Service")
    print("=" * 50)
    
    try:
        test_health_check()
        test_class_registration()
        test_administrative_request()
        test_graduation_request()
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the service. Make sure it's running on http://localhost:8000")
    except Exception as e:
        print(f"Error: {str(e)}")


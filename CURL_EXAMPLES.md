# CURL Examples

Các ví dụ curl để test ứng dụng Student Classification Service.

## Yêu cầu
- Server phải đang chạy tại `http://localhost:8000`

---

## 1. Health Check

### Linux/Mac (bash):
```bash
curl -X GET "http://localhost:8000/health" \
  -H "Content-Type: application/json"
```

### Windows (PowerShell):
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get -ContentType "application/json" | ConvertTo-Json
```

---

## 2. Class Registration Request (Đăng ký lớp học)

### Linux/Mac (bash):
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

### Windows (PowerShell):
```powershell
$body = @{
    internal = @{
        mail_id = "bhdn2ldnnx"
        id_record = "12n#a2@@"
    }
    title = "Đăng ký lớp học phần - Nhập môn lập trình"
    content = "Kính gửi phòng đào tạo,`n`nTôi là sinh viên Nguyễn Văn A, mã sinh viên: 22127259, lớp: 22CLC01, khóa 2022.`n`nTôi muốn đăng ký lớp học phần:`n- Môn học: Nhập môn lập trình (CSC101)`n- Mã lớp: CNPM01`n- Thứ: Thứ 2 (Monday)`n- Thời gian: 07:30:00`n`nXin cảm ơn!"
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/process" -Method Post -Body $body -ContentType "application/json" | ConvertTo-Json -Depth 10
```

### Windows (CMD với curl):
```cmd
curl -X POST "http://localhost:8000/process" -H "Content-Type: application/json" -d "{\"internal\":{\"mail_id\":\"bhdn2ldnnx\",\"id_record\":\"12n#a2@@\"},\"title\":\"Đăng ký lớp học phần - Nhập môn lập trình\",\"content\":\"Kính gửi phòng đào tạo,\\n\\nTôi là sinh viên Nguyễn Văn A, mã sinh viên: 22127259, lớp: 22CLC01, khóa 2022.\\n\\nTôi muốn đăng ký lớp học phần:\\n- Môn học: Nhập môn lập trình (CSC101)\\n- Mã lớp: CNPM01\\n- Thứ: Thứ 2 (Monday)\\n- Thời gian: 07:30:00\\n\\nXin cảm ơn!\"}"
```

---

## 3. Administrative Request (Yêu cầu hành chính)

### Linux/Mac (bash):
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

### Windows (PowerShell):
```powershell
$body = @{
    internal = @{
        mail_id = "email_789"
        id_record = "record_101"
    }
    title = "Yêu cầu cấp bản sao bảng điểm"
    content = "Kính gửi phòng đào tạo,`n`nTôi là sinh viên Jane Smith, mã sinh viên: ST2022001.`n`nTôi cần bản sao bảng điểm để nộp hồ sơ xin việc. Xin vui lòng hỗ trợ.`n`nCảm ơn!"
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/process" -Method Post -Body $body -ContentType "application/json" | ConvertTo-Json -Depth 10
```

---

## 4. Graduation Request (Yêu cầu tốt nghiệp)

### Linux/Mac (bash):
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

### Windows (PowerShell):
```powershell
$body = @{
    internal = @{
        mail_id = "email_456"
        id_record = "record_789"
    }
    title = "Đăng ký bảo vệ khóa luận tốt nghiệp"
    content = "Kính gửi phòng đào tạo,`n`nTôi là sinh viên Mike Johnson, mã sinh viên: ST2020001, sinh viên năm cuối ngành Khoa học Máy tính.`n`nTôi muốn đăng ký lịch bảo vệ khóa luận tốt nghiệp. Xin vui lòng sắp xếp lịch phù hợp.`n`nCảm ơn!"
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Uri "http://localhost:8000/process" -Method Post -Body $body -ContentType "application/json" | ConvertTo-Json -Depth 10
```

---

## 5. Sử dụng file script

### Linux/Mac:
```bash
chmod +x curl_examples.sh
./curl_examples.sh
```

### Windows PowerShell:
```powershell
.\curl_examples.ps1
```

---

## Response mẫu (Class Registration)

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

---

## Lưu ý

- Đảm bảo server đang chạy trước khi test
- Nếu gặp lỗi kết nối, kiểm tra xem server có đang chạy tại port 8000 không
- Với Windows, nếu không có curl, có thể dùng PowerShell `Invoke-RestMethod` hoặc cài đặt curl từ Windows 10 version 1803 trở lên


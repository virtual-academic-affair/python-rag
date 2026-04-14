#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "2. EMAIL CLASSIFICATION"

log_info "POST /api/email/process — label: classRegistration"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/email/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Xin dang ky mon hoc",
        "content": "Em muon dang ky mon Toan cao cap, ma mon MATH101, lop L01. Em la sinh vien nam 2, ma SV001, ten Nguyen Van A."
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — classRegistration"

log_info "POST /api/email/process — label: inquiry (AI draft reply)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/email/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Hoi ve dieu kien tot nghiep",
        "content": "Em muon hoi dieu kien de tot nghiep cua truong gom nhung gi? Em can bao nhieu tin chi va GPA toi thieu la bao nhieu?"
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — inquiry"

log_info "POST /api/email/process — label: task"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/email/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Yeu cau cap nhat diem hoc phan",
        "content": "Kinh gui phong dao tao, toi can phong cap nhat diem hoc phan Vat ly dai cuong cho sinh vien SV002 vi co sai sot trong he thong."
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — task"

log_info "POST /api/email/process — label: other"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/email/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Thong bao lich thi",
        "content": "Thong bao lich thi hoc ky II nam 2025-2026. Thi bat dau tu ngay 15/3/2026."
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — other"

log_info "POST /api/email/test/ingested — Simulate RabbitMQ ingest"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/email/test/ingested" \
    -H "Content-Type: application/json" \
    -d '{
        "pattern": "ingested",
        "data": {
            "messageId": 999,
            "subject": "Xin hoi ve lich hoc",
            "senderEmail": "student@example.com",
            "senderName": "Tran Thi B",
            "content": "Cho em hoi lich hoc mon Vat ly tuan toi nhu the nao?"
        }
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Test RabbitMQ ingested message"

#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "2. EMAIL CLASSIFICATION"

log_info "POST /api/email/process (Admin) — label: classRegistration"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/email/process" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d '{
        "messageId": 12345,
        "title": "Xin dang ky mon hoc",
        "content": "Em muon dang ky mon Toan cao cap, ma mon MATH101, lop L01. Em la sinh vien nam 2, ma SV001, ten Nguyen Van A."
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — classRegistration"

log_info "POST /api/email/process (Admin) — label: inquiry (AI draft reply)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/email/process" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d '{
        "messageId": 67890,
        "title": "Hoi ve dieu kien tot nghiep",
        "content": "Em muon hoi dieu kien de tot nghiep cua truong gom nhung gi? Em can bao nhieu tin chi va GPA toi thieu la bao nhieu?"
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — inquiry"

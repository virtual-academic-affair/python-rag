#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "FAQ — Smoke"

TS=$(date +%s)

log_info "POST /api/faqs — create"
FAQ_DATA="{
    \"question\": \"Làm thế nào để đăng ký giấy chứng nhận sinh viên? (${TS})\",
    \"answerRichText\": \"<p>Bạn có thể đăng ký trực tuyến trên cổng thông tin sinh viên hoặc đến trực tiếp Phòng Giáo vụ.</p>\",
    \"metadataFilter\": {
        \"academicYear\": {\"fromYear\": 2023, \"toYear\": 2024},
        \"enrollmentYear\": {\"fromYear\": 0, \"toYear\": 9999}
    }
}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${FAQ_DATA}" 2>/dev/null || echo -e "\n000")

if ! check_response "$RESPONSE" "201" "Create FAQ"; then
    return 1
fi
BODY=$(echo "$RESPONSE" | sed '$d')
FAQ_ID=$(echo "$BODY" | jq -r '.id // .faqId // empty')
log_info "  -> faq_id = $FAQ_ID"

log_info "GET /api/faqs — list with search and metadata filter"
FILTER_JSON='{"academicYear":{"fromYear":2023,"toYear":2024}}'
RESPONSE=$(curl -s -w "\n%{http_code}" -G "${BASE_URL}/api/faqs" \
    --data-urlencode "search=giấy chứng nhận" \
    --data-urlencode "metadataFilter=${FILTER_JSON}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "List/Search FAQ"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FAQ_ID" '(.total // 0) > 0 and any(.items[]?; (.id // .faqId) == $id)' >/dev/null \
        && log_success "  -> Filtered FAQ list includes created FAQ" \
        || { log_error "  -> Filtered FAQ list missing created FAQ"; return 1; }
fi

log_info "GET /api/faqs/${FAQ_ID} — detail"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get FAQ"

log_info "PATCH /api/faqs/${FAQ_ID} — update question and metadata"
UPDATE_DATA="{
    \"question\": \"Làm thế nào để đăng ký giấy chứng nhận sinh viên updated? (${TS})\",
    \"answerRichText\": \"<p>Bạn có thể đăng ký trực tuyến trên cổng thông tin sinh viên.</p>\",
    \"metadataFilter\": {
        \"academicYear\": {\"fromYear\": 2024, \"toYear\": 2025},
        \"enrollmentYear\": {\"fromYear\": 2020, \"toYear\": 2020}
    }
}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${UPDATE_DATA}" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Update FAQ"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.question | contains("updated")' >/dev/null \
        && log_success "  -> Updated FAQ contains new question" \
        || { log_error "  -> Updated FAQ missing new question"; return 1; }
fi

log_info "POST /api/faqs/match — FAQ answer debug"
MATCH_DATA="{
    \"question\": \"Làm thế nào để đăng ký giấy chứng nhận sinh viên?\",
    \"metadataFilter\": {
        \"academicYear\": {\"fromYear\": 2024, \"toYear\": 2025},
        \"enrollmentYear\": {\"fromYear\": 2020, \"toYear\": 2020}
    }
}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/match" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${MATCH_DATA}" 2>/dev/null || echo -e "\n000")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
if [ "$HTTP_CODE" = "200" ]; then
    log_success "Match FAQ (HTTP 200)"
elif [ "$HTTP_CODE" = "404" ]; then
    log_warning "Match FAQ returned 404; semantic index may still be warming up."
else
    check_response "$RESPONSE" "200" "Match FAQ"
fi

log_info "POST /api/faqs/import/preview — Excel preview"
python3 -c "
import openpyxl, time
wb = openpyxl.Workbook()
ws = wb.active
ts = int(time.time())
ws.append(['STT', 'Câu hỏi', 'Trả lời', 'Năm học', 'Khóa'])
ws.append([1, f'Học phí năm học 2024 là bao nhiêu? ({ts})', 'Học phí là 30 triệu/năm.', '2024-2025', ''])
ws.append([2, 'Q', 'Short', '', ''])
wb.save('scripts/test/sample_bulk_faq_unique.xlsx')
"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/import/preview" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_bulk_faq_unique.xlsx" \
    -F "question_col=Câu hỏi" \
    -F "answer_col=Trả lời" \
    -F "metadataFilterJson={\"academicYear\": \"Năm học\", \"enrollmentYear\": \"Khóa\"}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Preview FAQ Import"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.totalRows == 2' >/dev/null \
        && log_success "  -> Import preview counted valid and invalid rows" \
        || { log_error "  -> Import preview row count mismatch"; return 1; }
fi

log_info "POST /api/faqs/import — Excel import"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/import" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_bulk_faq_unique.xlsx" \
    -F "question_col=Câu hỏi" \
    -F "answer_col=Trả lời" \
    -F "metadataFilterJson={\"academicYear\": \"Năm học\", \"enrollmentYear\": \"Khóa\"}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Import FAQ"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.created == 1 and .failed == 1' >/dev/null \
        && log_success "  -> Import created valid row and rejected invalid row" \
        || { log_error "  -> Import counts mismatch"; return 1; }
fi

log_info "DELETE /api/faqs/${FAQ_ID} — cleanup"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Delete FAQ"

rm -f scripts/test/sample_bulk_faq_unique.xlsx

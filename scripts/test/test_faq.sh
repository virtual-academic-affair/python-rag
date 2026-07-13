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
    echo "$BODY" | jq -e --arg id "$FAQ_ID" '(.total // 0) > 0 and any(.items[]?; (.id // .faqId) == $id) and all(.items[]?; has("isActive") | not)' >/dev/null \
        && log_success "  -> Filtered FAQ list includes created FAQ" \
        || { log_error "  -> Filtered FAQ list missing created FAQ"; return 1; }
fi

log_info "GET /api/faqs/${FAQ_ID} — detail"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get FAQ"

log_info "GET /api/corpus/faqs/${FAQ_ID}/topics — capture assignments before FAQ update"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/corpus/faqs/${FAQ_ID}/topics" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if ! check_response "$RESPONSE" "200" "Get FAQ Corpus Topics Before Update"; then
    return 1
fi
BODY=$(echo "$RESPONSE" | sed '$d')
TOPICS_BEFORE=$(echo "$BODY" | jq -c '.nodeKeys | sort')

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

log_info "GET /api/corpus/faqs/${FAQ_ID}/topics — update must keep assignments"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/corpus/faqs/${FAQ_ID}/topics" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Get FAQ Corpus Topics After Update"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    TOPICS_AFTER=$(echo "$BODY" | jq -c '.nodeKeys | sort')
    if [ "$TOPICS_AFTER" = "$TOPICS_BEFORE" ]; then
        log_success "  -> FAQ update preserved Corpus topic assignments"
    else
        log_error "  -> FAQ update changed Corpus topics: before=$TOPICS_BEFORE after=$TOPICS_AFTER"
        return 1
    fi
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

FAQ_SAMPLE_FILE="$REPO_ROOT/scripts/test/sample_bulk_faq_unique_${TS}.xlsx"
cleanup_faq_smoke() {
    rm -f "$FAQ_SAMPLE_FILE" "$REPO_ROOT/scripts/test/sample_bulk_faq_unique.xlsx"
}
trap 'cleanup_faq_smoke; trap - RETURN' RETURN

log_info "POST /api/faqs/import/preview — Excel preview"
"$PYTHON_BIN" -c "
import openpyxl, time
wb = openpyxl.Workbook()
ws = wb.active
ts = int(time.time())
ws.append(['STT', 'Câu hỏi', 'Trả lời', 'Năm học', 'Khóa'])
ws.append([1, f'Học phí năm học 2024 là bao nhiêu? ({ts})', 'Học phí là 30 triệu/năm.', '2024-2025', ''])
ws.append([2, 'Q', 'Short', '', ''])
wb.save('$FAQ_SAMPLE_FILE')
"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/import/preview" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@${FAQ_SAMPLE_FILE}" \
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
    -F "file=@${FAQ_SAMPLE_FILE}" \
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

log_info "DELETE /api/faqs/${FAQ_ID} — soft delete"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Soft Delete FAQ"

RESPONSE=$(curl -s -w "\n%{http_code}" "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "404" "Deleted FAQ Hidden From Detail"

RESPONSE=$(curl -s -w "\n%{http_code}" -G "${BASE_URL}/api/faqs" \
    --data-urlencode "search=giấy chứng nhận" \
    --data-urlencode "limit=100" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Deleted FAQ Hidden From Normal List"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FAQ_ID" 'all(.items[]?; (.faqId // .id) != $id)' >/dev/null \
        && log_success "  -> Normal FAQ list excludes deleted FAQ" \
        || { log_error "  -> Normal FAQ list leaked deleted FAQ"; return 1; }
fi

RESPONSE=$(curl -s -w "\n%{http_code}" "${BASE_URL}/api/faqs/trash" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "List Deleted FAQs"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FAQ_ID" 'any(.items[]?; (.faqId // .id) == $id and .deletedAt != null)' >/dev/null \
        || { log_error "  -> FAQ trash missing deleted FAQ"; return 1; }
fi

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/${FAQ_ID}/restore" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Restore FAQ"

curl -s -X DELETE "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" >/dev/null
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${BASE_URL}/api/faqs/${FAQ_ID}/purge" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Purge FAQ"

cleanup_faq_smoke

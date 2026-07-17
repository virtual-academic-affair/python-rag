#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "5. FILE MANAGEMENT — Smoke"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
UPLOADS_DIR="$REPO_ROOT/scripts/uploads"
mkdir -p "$UPLOADS_DIR"
TEST_FILE="${UPLOADS_DIR}/test_doc_${TIMESTAMP}.txt"
cat > "$TEST_FILE" << EOF
QUY ĐỊNH VỀ ĐIỀU KIỆN XÉT TỐT NGHIỆP

Mã tài liệu smoke test: ${TIMESTAMP}

#1. Điều kiện xét tốt nghiệp
Sinh viên được xét tốt nghiệp khi tích lũy đủ số tín chỉ theo chương trình đào tạo,
hoàn thành các học phần bắt buộc, không còn nợ học phí, và đạt điểm trung bình tích lũy
theo quy định của nhà trường.

#2. Chuẩn đầu ra
Sinh viên phải hoàn thành chuẩn đầu ra ngoại ngữ, tin học và các yêu cầu bắt buộc khác
trước thời điểm Hội đồng xét tốt nghiệp kiểm tra hồ sơ.

#3. Hồ sơ xét tốt nghiệp
Sinh viên kiểm tra kết quả học tập và nộp hồ sơ xét tốt nghiệp theo thông báo chính thức
của Phòng Giáo vụ.
EOF

log_info "POST /api/files — admin upload"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -H "${AUTH_HEADER}" \
    -F "file=@${TEST_FILE}" \
    -F "displayName=Test Doc Điều kiện xét tốt nghiệp ${TIMESTAMP}" \
    -F 'customMetadata={"type":"cong_van","academicYear":{"fromYear":2025,"toYear":2026}}' \
    2>/dev/null || echo -e "\n000")

if ! check_response "$RESPONSE" "201" "Upload File"; then
    rm -f "$TEST_FILE"
    return 1
fi

BODY=$(echo "$RESPONSE" | sed '$d')
FILE_ID=$(echo "$BODY" | jq -r '.fileId // empty')
echo "$FILE_ID" > "$OUTPUT_DIR/last_file_id.txt"
log_info "  -> file_id = $FILE_ID"

log_info "Waiting for file $FILE_ID to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0
STATUS="uploading"
while [ "$STATUS" != "ready" ] && [ "$STATUS" != "failed" ] && [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
    sleep 2
    DETAIL_BODY=$(curl -s -H "${AUTH_HEADER}" "${API_URL}/files/${FILE_ID}" 2>/dev/null || echo '{}')
    STATUS=$(echo "$DETAIL_BODY" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
    RETRY_COUNT=$((RETRY_COUNT + 1))
    log_info "  -> Current status: $STATUS (attempt $RETRY_COUNT/$MAX_RETRIES)"
done

if [ "$STATUS" != "ready" ]; then
    log_error "File $FILE_ID failed to reach ready status (final: $STATUS)"
    rm -f "$TEST_FILE"
    return 1
fi
log_success "File $FILE_ID is ready"

FILTER_JSON='{"academicYear":{"fromYear":2025,"toYear":2026}}'
ENCODED_FILTER=$("$PYTHON_BIN" -c "import urllib.parse; print(urllib.parse.quote('''$FILTER_JSON'''))")
log_info "GET /api/files — student list with keyword/status/metadata/lecturerOnly filters"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?limit=5&keywords=Test%20Doc&fileStatus=ready&lecturerOnly=false&metadataFilter=${ENCODED_FILTER}" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Student List/Search/Filter Files"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FILE_ID" '
        (.files // []) as $files
        | any($files[]?; .fileId == $id and .status == "ready" and .lecturerOnly == false)
          and all($files[]?; has("tableOfContents") | not)
    ' >/dev/null \
        && log_success "  -> List includes READY file and omits tableOfContents" \
        || { log_error "  -> File list shape/filter mismatch"; return 1; }
fi

log_info "GET /api/files/${FILE_ID} — student detail"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Student Get File Detail"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e 'has("tableOfContents")' >/dev/null \
        && log_success "  -> Detail keeps tableOfContents" \
        || { log_error "  -> Detail missing tableOfContents"; return 1; }
fi

log_info "GET /api/files/${FILE_ID}/download — student original download"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}/download" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Student Download Original"

log_info "GET /api/files/${FILE_ID}/download?format=markdown — student markdown download"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}/download?format=markdown" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Student Download Markdown"

log_info "GET /api/toc-tree/${FILE_ID} — student TOC"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/toc-tree/${FILE_ID}" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Student Get TOC Tree"

log_info "PATCH /api/files/${FILE_ID} — student forbidden"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/files/${FILE_ID}" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "{\"displayName\":\"Student Should Not Update ${TIMESTAMP}\"}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "403" "Student Update File Forbidden"

log_info "DELETE /api/files/${FILE_ID} — student forbidden"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/${FILE_ID}" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "403" "Student Delete File Forbidden"

log_info "PATCH /api/files/${FILE_ID} — admin update name, metadata and lecturerOnly"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/files/${FILE_ID}" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{\"displayName\":\"Updated File ${TIMESTAMP}\",\"lecturerOnly\":true,\"customMetadata\":{\"academicYear\":{\"fromYear\":2024,\"toYear\":2025},\"type\":\"quyet_dinh\"}}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Admin Update File"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.displayName | contains("Updated File")' >/dev/null \
        && log_success "  -> Updated response contains new display name" \
        || { log_error "  -> Updated response missing new display name"; return 1; }
fi

log_info "GET /api/files — lecture exact lecturerOnly filter; fileStatus cannot bypass READY rule"
RESPONSE=$(curl -s -w "\n%{http_code}" -G "${API_URL}/files" \
    --data-urlencode "keywords=Updated File ${TIMESTAMP}" \
    --data-urlencode "lecturerOnly=true" \
    --data-urlencode "fileStatus=processing" \
    -H "${LECTURE_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Lecture List Lecturer-only READY Files"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FILE_ID" '
        any(.files[]?; .fileId == $id and .status == "ready" and .lecturerOnly == true and (has("tableOfContents") | not))
    ' >/dev/null \
        && log_success "  -> Lecture sees lecturer-only file as READY without TOC" \
        || { log_error "  -> Lecture lecturerOnly/status filter mismatch"; return 1; }
fi

log_info "GET /api/files — student cannot opt into lecturerOnly=true"
RESPONSE=$(curl -s -w "\n%{http_code}" -G "${API_URL}/files" \
    --data-urlencode "keywords=Updated File ${TIMESTAMP}" \
    --data-urlencode "lecturerOnly=true" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Student Cannot List Lecturer-only Files"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FILE_ID" 'all(.files[]?; .fileId != $id)' >/dev/null \
        && log_success "  -> Student lecturerOnly=true did not widen access" \
        || { log_error "  -> Student could list lecturer-only file"; return 1; }
fi

RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
    -H "${LECTURE_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Lecture Get Lecturer-only File Detail"

RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "404" "Student Lecturer-only File Hidden From Detail"

log_info "GET /api/files/000000000000000000000000 — not found"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/000000000000000000000000" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "404" "Get File Not Found"

log_info "DELETE /api/files/${FILE_ID} — admin soft delete"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/${FILE_ID}" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Admin Soft Delete File"

RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "404" "Deleted File Hidden From Detail"

RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/trash?lecturerOnly=true" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "List Deleted Files"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FILE_ID" 'any(.files[]?; .fileId == $id and .deletedAt != null and .lecturerOnly == true and (has("tableOfContents") | not))' >/dev/null \
        || { log_error "  -> File trash missing deleted file"; return 1; }
fi

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files/${FILE_ID}/restore" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Restore File"

curl -s -X DELETE "${API_URL}/files/${FILE_ID}" -H "${AUTH_HEADER}" >/dev/null
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/${FILE_ID}/purge" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Purge File"

rm -f "$TEST_FILE"

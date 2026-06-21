#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "5. FILE MANAGEMENT — Smoke"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
UPLOADS_DIR="scripts/uploads"
mkdir -p "$UPLOADS_DIR"
TEST_FILE="${UPLOADS_DIR}/test_doc_${TIMESTAMP}.txt"
echo "Content of test doc ${TIMESTAMP}" > "$TEST_FILE"

log_info "POST /api/files — admin upload"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -H "${AUTH_HEADER}" \
    -F "file=@${TEST_FILE}" \
    -F "displayName=Test Doc ${TIMESTAMP}" \
    -F 'customMetadata={"type":"cong_van","academicYear":{"fromYear":2025,"toYear":2026}}' \
    2>/dev/null || echo -e "\n000")

if ! check_response "$RESPONSE" "201" "Upload File"; then
    rm -f "$TEST_FILE"
    return 1
fi

BODY=$(echo "$RESPONSE" | sed '$d')
FILE_ID=$(echo "$BODY" | jq -r '.fileId // empty')
echo "$FILE_ID" > scripts/test_results/last_file_id.txt
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
ENCODED_FILTER=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$FILTER_JSON'''))")
log_info "GET /api/files — student list with keyword/status/metadata filters"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?limit=5&keywords=Test%20Doc&fileStatus=ready&metadataFilter=${ENCODED_FILTER}" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Student List/Search/Filter Files"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FILE_ID" 'any((.items // .files // [])[]?; (.fileId // .id) == $id and .status == "ready")' >/dev/null \
        && log_success "  -> Filtered list includes uploaded ready file" \
        || { log_error "  -> Filtered list missing uploaded ready file"; return 1; }
fi

log_info "GET /api/files/${FILE_ID} — student detail"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
    -H "${STUDENT_AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Student Get File Detail"

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

log_info "PATCH /api/files/${FILE_ID} — admin update name and metadata"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/files/${FILE_ID}" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{\"displayName\":\"Updated File ${TIMESTAMP}\",\"customMetadata\":{\"academicYear\":{\"fromYear\":2024,\"toYear\":2025},\"type\":\"quyet_dinh\"}}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Admin Update File"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.displayName | contains("Updated File")' >/dev/null \
        && log_success "  -> Updated response contains new display name" \
        || { log_error "  -> Updated response missing new display name"; return 1; }
fi

log_info "GET /api/files/000000000000000000000000 — not found"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/000000000000000000000000" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "404" "Get File Not Found"

log_info "DELETE /api/files/${FILE_ID} — admin cleanup"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/${FILE_ID}" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Admin Delete File"

rm -f "$TEST_FILE"

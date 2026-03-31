#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "5. FILE MANAGEMENT"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create test files if they don't exist
UPLOADS_DIR="scripts/uploads"
mkdir -p "$UPLOADS_DIR"
TEST_FILE="${UPLOADS_DIR}/test_doc_${TIMESTAMP}.txt"
TEST_FILE_2="${UPLOADS_DIR}/test_doc_2_${TIMESTAMP}.txt"
echo "Content of test doc 1 ${TIMESTAMP}" > "$TEST_FILE"
echo "Content of test doc 2 ${TIMESTAMP}" > "$TEST_FILE_2"

# 1. Upload file
log_info "POST /api/files — Upload file (require_admin)"
if [ -s scripts/test_results/last_store_id.txt ]; then
    STORE_ID=$(cat scripts/test_results/last_store_id.txt)
fi

UPLOAD_ARGS=(-F "file=@${TEST_FILE}" -F "displayName=Test Doc ${TIMESTAMP}")
if [ -n "$STORE_ID" ]; then
    UPLOAD_ARGS+=(-F "storeId=${STORE_ID}")
fi
UPLOAD_ARGS+=(-F 'customMetadata={"department":["dao_tao"],"accessScope":["student"],"academicYear":["2025-2026"]}')

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -H "${AUTH_HEADER}" \
    "${UPLOAD_ARGS[@]}" 2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "201" "Upload File"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    FILE_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fileId',''))" 2>/dev/null || echo "")
    log_info "  -> file_id = $FILE_ID"
    echo "$FILE_ID" > scripts/test_results/last_file_id.txt
fi

# 2. List files with filters
log_info "GET /api/files — Default store (should not pass storeId)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?limit=5" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files (Default Store)"

if [ -n "$STORE_ID" ]; then
    log_info "GET /api/files/admin?storeId=${STORE_ID} — Admin list by store"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/admin?storeId=${STORE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Admin List Files by storeId"
fi

log_info "GET /api/files?keywords=Quy+che — Search by displayName"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?keywords=Quy+che" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files by keywords"

log_info "GET /api/files?fileStatus=active — Filter by status"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?fileStatus=active" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files by status=active"

log_info "GET /api/files?metadataFilter=... — Filter by metadata"
FILTER_JSON='{"academicYear":["2025-2026", "2024-2025"]}'
ENCODED_FILTER=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$FILTER_JSON'''))")
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?metadataFilter=${ENCODED_FILTER}" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files by metadataFilter"

# 3. Check Sync
log_info "GET /api/files/check-sync — Comparison across DB, R2, Gemini"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/check-sync" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Check Sync Status"

# 4. Detail & Download
if [ -s scripts/test_results/last_file_id.txt ]; then
    FILE_ID=$(cat scripts/test_results/last_file_id.txt)
    log_info "GET /api/files/${FILE_ID} — Detail"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Get File Detail"
    
    log_info "GET /api/files/${FILE_ID}/download — Download"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/files/${FILE_ID}/download" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        log_success "Download File (HTTP 200)"
    else
        log_error "Download File — Expected 200, got $HTTP_CODE"
    fi
    
    log_info "PATCH /api/files/${FILE_ID} — Cap nhat display_name"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/files/${FILE_ID}" \
        -H "Content-Type: application/json" \
        -H "${AUTH_HEADER}" \
        -d "{ \"displayName\": \"Updated File Name ${TIMESTAMP}\" }" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Update File Display Name"
    
    log_info "POST /api/files — Upload temp file de xoa"
    TEMP_FILE="${UPLOADS_DIR}/temp_doc_delete_${TIMESTAMP}.txt"
    echo "Content to delete" > "$TEMP_FILE"
    
    TEMP_UPLOAD_ARGS=(-F "file=@${TEMP_FILE}" -F "displayName=Temp File ${TIMESTAMP}")
    if [ -n "$STORE_ID" ]; then
        TEMP_UPLOAD_ARGS+=(-F "storeId=${STORE_ID}")
    fi
    TEMP_UPLOAD_ARGS+=(-F 'customMetadata={"department":["dao_tao"],"accessScope":["student"],"academicYear":["2025-2026"]}')
    
    TEMP_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
        -H "${AUTH_HEADER}" \
        "${TEMP_UPLOAD_ARGS[@]}" 2>/dev/null || echo -e "\n000")
        
    if check_response "$TEMP_RESPONSE" "201" "Upload Temp File"; then
        TEMP_BODY=$(echo "$TEMP_RESPONSE" | sed '$d')
        TEMP_FILE_ID=$(echo "$TEMP_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fileId',''))" 2>/dev/null || echo "")
        
        log_info "DELETE /api/files/${TEMP_FILE_ID} — Xoa file don le"
        RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/${TEMP_FILE_ID}" \
            -H "${AUTH_HEADER}" \
            2>/dev/null || echo -e "\n000")
        check_response "$RESPONSE" "204" "Delete File by ID"
    fi
    rm -f "$TEMP_FILE"
fi

# 5. Batch Upload
log_info "POST /api/files/batch — Batch upload 2 files (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files/batch" \
    -H "${AUTH_HEADER}" \
    -F "files=@${TEST_FILE}" \
    -F "files=@${TEST_FILE_2}" \
    -F "displayNames=[\"Batch 1 ${TIMESTAMP}\", \"Batch 2 ${TIMESTAMP}\"]" \
    -F 'metadataList=[{"department":["dao_tao"],"accessScope":["student"],"academicYear":["2025-2026"]},{"department":["khcn"],"accessScope":["student"],"academicYear":["2025-2026"]}]' \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "201" "Batch Upload Files"

# 6. Trigger Sync
log_info "POST /api/files/sync — Trigger file sync across R2/Gemini"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files/sync" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Sync Files"

# 7. Delete all in store
if [ -n "$STORE_ID" ]; then
    log_info "DELETE /api/files/all?storeId=${STORE_ID} — Xoa tat ca file trong store"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/all?storeId=${STORE_ID}" \
        -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Delete All Files in Store"
fi

# 8. Error cases
log_info "GET /api/files/000000000000000000000000 — Not found (expect 404)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/000000000000000000000000" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "404" "Get File — not found"

log_info "POST /api/files — Unauthorized (expect 401)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -F "file=@${TEST_FILE}" \
    -F "displayName=Unauth" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "401" "Upload File — no token"

# Cleanup temp files
rm "$TEST_FILE" "$TEST_FILE_2"

#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "5. FILE MANAGEMENT (Store-free Modular)"

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

UPLOAD_ARGS=(-F "file=@${TEST_FILE}" -F "displayName=Test Doc ${TIMESTAMP}")
UPLOAD_ARGS+=(-F 'customMetadata={"type":"cong_van","academicYear":{"fromYear":2025,"toYear":2026}}')

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -H "${AUTH_HEADER}" \
    "${UPLOAD_ARGS[@]}" 2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "201" "Upload File"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    FILE_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fileId',''))" 2>/dev/null || echo "")
    log_info "  -> file_id = $FILE_ID"
    echo "$FILE_ID" > scripts/test_results/last_file_id.txt

    # Wait for file to be ready
    log_info "Waiting for file $FILE_ID to be 'ready'..."
    MAX_RETRIES=30
    RETRY_COUNT=0
    STATUS="uploading"
    
    while [ "$STATUS" != "ready" ] && [ "$STATUS" != "failed" ] && [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
        sleep 2
        DETAIL_RESPONSE=$(curl -s -H "${AUTH_HEADER}" "${API_URL}/files/${FILE_ID}")
        STATUS=$(echo "$DETAIL_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "unknown")
        RETRY_COUNT=$((RETRY_COUNT + 1))
        log_info "  -> Current status: $STATUS (attempt $RETRY_COUNT/$MAX_RETRIES)"
    done

    if [ "$STATUS" = "ready" ]; then
        log_success "File $FILE_ID is ready"
        
        # 1.1 Verify TOC Tree API
        log_info "GET /api/toc-tree/${FILE_ID} — New TOC Schema"
        RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/toc-tree/${FILE_ID}" \
            -H "${AUTH_HEADER}" \
            2>/dev/null || echo -e "\n000")
        check_response "$RESPONSE" "200" "Get TOC Tree"
    else
        log_error "File $FILE_ID failed to reach ready status (final: $STATUS)"
    fi
fi

# 2. List files with filters
log_info "GET /api/files — List files (Auth user)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?limit=5" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files"

log_info "GET /api/files — Admin list (using Admin header)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?limit=5" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Admin List Files"

log_info "GET /api/files?keywords=Test — Search by displayName"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?keywords=Test" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files by keywords"

log_info "GET /api/files?fileStatus=ready — Filter by status"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?fileStatus=ready" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files by status=ready"

log_info "GET /api/files?metadataFilter=... — Filter by metadata (Object format)"
FILTER_JSON='{"academicYear":{"fromYear":2025,"toYear":2026}}'
ENCODED_FILTER=$(python3 -c "import urllib.parse; print(urllib.parse.quote('''$FILTER_JSON'''))")
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?metadataFilter=${ENCODED_FILTER}" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files by metadataFilter"

# 4. Detail & Update
if [ -s scripts/test_results/last_file_id.txt ]; then
    FILE_ID=$(cat scripts/test_results/last_file_id.txt)
    
    log_info "GET /api/files/${FILE_ID} — Detail"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Get File Detail"
    
    log_info "PATCH /api/files/${FILE_ID} — Update display_name"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/files/${FILE_ID}" \
        -H "Content-Type: application/json" \
        -H "${AUTH_HEADER}" \
        -d "{ \"displayName\": \"Updated File Name ${TIMESTAMP}\" }" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Update File Display Name"

    log_info "PATCH /api/files/${FILE_ID} — Update display_name & customMetadata"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/files/${FILE_ID}" \
        -H "Content-Type: application/json" \
        -H "${AUTH_HEADER}" \
        -d "{ \"displayName\": \"Full Update ${TIMESTAMP}\", \"customMetadata\": { \"academicYear\": {\"fromYear\": 2025, \"toYear\": 2026}, \"type\": \"quyet_dinh\" } }" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Update File Metadata"
    
    log_info "POST /api/files — Upload temp file to delete"
    TEMP_FILE="${UPLOADS_DIR}/temp_doc_delete_${TIMESTAMP}.txt"
    echo "Content to delete" > "$TEMP_FILE"
    
    TEMP_UPLOAD_ARGS=(-F "file=@${TEMP_FILE}" -F "displayName=Temp File ${TIMESTAMP}")
    TEMP_UPLOAD_ARGS+=(-F 'customMetadata={"type":"cong_van"}')
    
    TEMP_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
        -H "${AUTH_HEADER}" \
        "${TEMP_UPLOAD_ARGS[@]}" 2>/dev/null || echo -e "\n000")
        
    if check_response "$TEMP_RESPONSE" "201" "Upload Temp File"; then
        TEMP_BODY=$(echo "$TEMP_RESPONSE" | sed '$d')
        TEMP_FILE_ID=$(echo "$TEMP_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fileId',''))" 2>/dev/null || echo "")
        
        log_info "DELETE /api/files/${TEMP_FILE_ID} — Delete single file"
        RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/${TEMP_FILE_ID}" \
            -H "${AUTH_HEADER}" \
            2>/dev/null || echo -e "\n000")
        check_response "$RESPONSE" "204" "Delete File by ID"
    fi
    rm -f "$TEMP_FILE"

    # Ported from main: Download Markdown & Metadata Endpoint
    log_info "GET /api/files/${FILE_ID}/download?format=markdown — Download Markdown"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}/download?format=markdown" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Download Markdown"

    log_info "PATCH /api/files/${FILE_ID} — Update metadata via unified endpoint"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/files/${FILE_ID}" \
        -H "Content-Type: application/json" \
        -H "${AUTH_HEADER}" \
        -d "{ \"customMetadata\": { \"academicYear\": {\"fromYear\": 2024, \"toYear\": 2025}, \"type\": \"cong_van\" } }" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Update File Metadata (unified endpoint)"
    
    log_info "GET /api/files/${FILE_ID} — Verify updated metadata"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    if [[ "$RESPONSE" == *"2024"* ]]; then
        log_success "Metadata update verification success"
    else
        log_error "Metadata update verification failed: $RESPONSE"
        exit 1
    fi
fi

# 5. Batch Upload
log_info "POST /api/files/batch — Batch upload 2 files (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files/batch" \
    -H "${AUTH_HEADER}" \
    -F "files=@${TEST_FILE}" \
    -F "files=@${TEST_FILE_2}" \
    -F "displayNames=[\"Batch 1 ${TIMESTAMP}\", \"Batch 2 ${TIMESTAMP}\"]" \
    -F 'metadataList=[{"type":"cong_van","academicYear":{"fromYear":2025,"toYear":2026}},{"type":"quyet_dinh","academicYear":{"fromYear":2025,"toYear":2026}}]' \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "201" "Batch Upload Files"

# Error cases
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
rm -f "$TEST_FILE" "$TEST_FILE_2"

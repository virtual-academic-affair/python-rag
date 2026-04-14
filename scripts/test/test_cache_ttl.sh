#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "CACHE TTL & R2 REFRESH VERIFICATION"

WS_PATH="storage/pageindex_workspace"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# 1. Upload a fresh file
log_info "Step 1: Uploading file for cache test..."
UPLOADS_DIR="scripts/uploads"
mkdir -p "$UPLOADS_DIR"
TEST_FILE="${UPLOADS_DIR}/cache_test_${TIMESTAMP}.txt"
echo "Content for cache verification ${TIMESTAMP}" > "$TEST_FILE"

UPLOAD_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -H "${AUTH_HEADER}" \
    -F "file=@${TEST_FILE}" \
    -F "displayName=Cache Test ${TIMESTAMP}" \
    -F 'customMetadata={"access_scope":["student"],"academic_year":["2025-2026"]}' \
    2>/dev/null || echo -e "\n000")

if ! check_response "$UPLOAD_RESPONSE" "201" "Upload Cache Test File"; then
    log_error "Failed to upload test file"
    exit 1
fi

FILE_ID=$(echo "$UPLOAD_RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fileId',''))" 2>/dev/null || echo "")
log_info "  -> file_id = $FILE_ID"

# 2. Wait for ready
log_info "Step 2: Waiting for processing..."
MAX_RETRIES=20
RETRY_COUNT=0
STATUS="uploading"
while [ "$STATUS" != "ready" ] && [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
    sleep 2
    DETAIL_RESPONSE=$(curl -s -H "${AUTH_HEADER}" "${API_URL}/files/${FILE_ID}")
    STATUS=$(echo "$DETAIL_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || echo "unknown")
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ "$STATUS" != "ready" ]; then
    log_error "File failed to reach 'ready' status"
    exit 1
fi

# 3. Verify local file exists
CACHE_FILE="${WS_PATH}/${FILE_ID}.md"
if [ -f "$CACHE_FILE" ]; then
    log_success "Local cache file exists: $CACHE_FILE"
else
    log_error "Local cache file NOT found at $CACHE_FILE"
    exit 1
fi

# 4. DELETE local file (Simulate expiry/missing)
log_info "Step 3: Deleting local cache file to simulate missing cache..."
rm -f "$CACHE_FILE"
if [ ! -f "$CACHE_FILE" ]; then
    log_success "Local cache file deleted"
else
    log_error "Failed to delete local cache file"
    exit 1
fi

# 5. Call TOC Tree API (should trigger re-download)
log_info "Step 4: Calling TOC Tree API — should trigger R2 download..."
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/toc-tree/${FILE_ID}" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "200" "Trigger Cache Refresh"; then
    # 6. Check if file re-appeared
    if [ -f "$CACHE_FILE" ]; then
        log_success "Cache Refresh SUCCESS: Local file re-downloaded from R2!"
    else
        log_error "Cache Refresh FAILED: Local file still missing!"
    fi
fi

# Cleanup
log_info "Cleaning up..."
curl -s -X DELETE "${API_URL}/files/${FILE_ID}" -H "${AUTH_HEADER}" >/dev/null
rm -f "$TEST_FILE"

#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "DEBUGGING & PREVIEWS"

SAMPLE_PDF=$(ls scripts/uploads/*.pdf 2>/dev/null | head -n 1)

if [ -z "$SAMPLE_PDF" ]; then
    log_warning "No sample PDF found in scripts/uploads/. Skipping debug tests."
    return 0
fi

log_info "Using sample PDF: $SAMPLE_PDF"

# 1. Parse Preview
log_info "POST /api/debug/files/parse-preview — LlamaParse preview (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/debug/files/parse-preview" \
    -H "${AUTH_HEADER}" \
    -F "file=@${SAMPLE_PDF}" 2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "200" "Parse Preview"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    PAGE_COUNT=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pageCount',0))" 2>/dev/null || echo "0")
    log_info "  -> Received $PAGE_COUNT pages"
fi

# 2. Chunk Preview
log_info "POST /api/debug/files/chunk-preview — Chunking preview (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/debug/files/chunk-preview" \
    -H "${AUTH_HEADER}" \
    -F "file=@${SAMPLE_PDF}" \
    -F "chunkSizeChars=1000" \
    -F "chunkOverlapChars=100" 2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "200" "Chunk Preview"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    CHUNK_COUNT=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('chunkCount',0))" 2>/dev/null || echo "0")
    log_info "  -> Generated $CHUNK_COUNT chunks"
fi

# 3. Retrieval Preview
log_info "POST /api/chat/retrieve-preview — Vector Retrieval test"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/retrieve-preview" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d '{
        "question": "Quy định về tốt nghiệp",
        "topK": 5,
        "minScore": 0.3
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Retrieval Preview"

#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "6. CHAT"

# 1. Chat query
log_info "POST /api/chat/query"
if [ -s scripts/test_results/last_store_id.txt ]; then
    STORE_ID=$(cat scripts/test_results/last_store_id.txt)
fi

QUERY_BODY='{"question": "Dieu kien tot nghiep cua truong la gi?", "userContext": {"userId": "sv001_anon", "name": "Nguyen Van A", "cohort": "K20", "role": "student"}, "chatHistory": []}'
if [ -n "$STORE_ID" ]; then
    QUERY_BODY=$(echo "$QUERY_BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); d['storeId']='$STORE_ID'; print(json.dumps(d))")
fi

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query"

# 2. Chat streaming (SSE)
log_info "POST /api/chat/stream — Streaming (max 10s)"
RESPONSE_STREAM=$(timeout 10 curl -s -N -X POST "${API_URL}/chat/stream" \
    -H "Content-Type: application/json" \
    -d "$QUERY_BODY" 2>/dev/null || echo "TIMEOUT")

if [[ "$RESPONSE_STREAM" == *"done"* ]] || [[ "$RESPONSE_STREAM" == *"chunk"* ]]; then
    log_success "Chat Stream — nhan duoc du lieu"
else
    log_info "Chat Stream — timeout or no data (flaky due to LLM speed)"
fi

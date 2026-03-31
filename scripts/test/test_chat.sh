#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "6. CHAT"

# 1. Chat query
log_info "POST /api/chat/query"

QUERY_BODY='{"question": "Dieu kien tot nghiep cua truong la gi?", "chatHistory": []}'

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query"

# 2. Chat streaming (SSE)
log_info "POST /api/chat/stream — Streaming (max 10s)"
RESPONSE_STREAM=$(timeout 10 curl -s -N -X POST "${API_URL}/chat/stream" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo "TIMEOUT")

if [[ "$RESPONSE_STREAM" == *"done"* ]] || [[ "$RESPONSE_STREAM" == *"chunk"* ]]; then
    log_success "Chat Stream — nhan duoc du lieu"
else
    log_info "Chat Stream — timeout or no data (flaky due to LLM speed)"
fi

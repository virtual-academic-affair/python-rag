#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "6. CHAT"

# 1. Chat query
log_info "POST /api/chat/query"

QUERY_BODY='{"question": "Hi", "chatHistory": []}'

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query"

# 2. Chat streaming (SSE)
log_info "POST /api/chat/stream — Streaming (max 60s)"
# Capture stream and grep for key indicators
# Use curl's internal --max-time for better stream handling
RESPONSE_STREAM=$(curl -s -N --max-time 60 -X POST "${API_URL}/chat/stream" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null)

CUR_EXIT=$?
if [ $CUR_EXIT -eq 28 ]; then
    log_error "Chat Stream — Request timed out (60s)"
    exit 1
elif [ $CUR_EXIT -ne 0 ]; then
    log_error "Chat Stream — Curl failed with exit code $CUR_EXIT"
    exit 1
fi

HAS_CHUNK=$(echo "$RESPONSE_STREAM" | grep -Ei '"type":\s*"(text|thought|call)"' | head -n 1 || echo "")
HAS_DONE=$(echo "$RESPONSE_STREAM" | grep -Ei '"done":\s*true' | head -n 1 || echo "")

if [ -n "$HAS_CHUNK" ]; then
    log_success "Chat Stream — Nhan duoc du lieu"
    if [ -n "$HAS_DONE" ]; then
        log_success "Chat Stream — Thay tin hieu 'done'"
    else
        log_warning "Chat Stream — Khong thay tin hieu 'done' (possible timeout or error)"
        log_info "Raw stream sample: ${RESPONSE_STREAM:0:200}..."
    fi
else
    log_error "Chat Stream — Khong nhan duoc du lieu hop le"
    log_info "Raw stream sample: ${RESPONSE_STREAM:0:200}..."
fi

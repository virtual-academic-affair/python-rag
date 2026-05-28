#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "6. CHAT"

# 1. Chat query - Small Talk (Bypass RAG)
log_info "POST /api/chat/query — Small Talk"
QUERY_BODY='{"question": "Xin chào, bạn là ai?", "chatHistory": []}'
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — Small Talk"
# Verify source is 'llm' and no sources provided (bypass RAG)
echo "$RESPONSE" | sed '$d' | grep -q '"source":[[:space:]]*"llm"' && log_success "  -> Source check: llm (Correct)" || log_warning "  -> Source check failed or different"

# 2. Chat query - FAQ Match (Direct answer)
log_info "POST /api/chat/query — FAQ Match"
QUERY_BODY='{"question": "Thủ tục xin bảo lưu kết quả học tập?", "chatHistory": []}'
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — FAQ Match"
# Verify source is 'faq'
echo "$RESPONSE" | sed '$d' | grep -q '"source":[[:space:]]*"faq"' && log_success "  -> Source check: faq (Correct)" || log_warning "  -> Source check failed or different"

# 3. Chat query - RAG Search (Document-based)
log_info "POST /api/chat/query — RAG Search"
QUERY_BODY='{"question": "Điều kiện tốt nghiệp của trường là gì, GPA bao nhiêu?", "chatHistory": []}'
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — RAG Search"
# Verify has sources
echo "$RESPONSE" | sed '$d' | grep -q '"citationId"' && log_success "  -> Citation check: Found sources (Correct)" || log_warning "  -> Citation check failed: No sources found"

# 3.5. Chat query - RAG Search with Customizations (Rich Text & HTML Citations)
log_info "POST /api/chat/query — RAG Search (Rich Text & HTML Citations)"
QUERY_BODY='{"question": "Quy chế là gì?", "chatHistory": [], "toRichText": true, "resolveCitations": true, "citationLinkType": "html"}'
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — RAG Search (Customizations)"
# Verify answer contains HTML tags (Rich Text)
echo "$RESPONSE" | sed '$d' | grep -q '<p>' && log_success "  -> Rich Text check: answer contains HTML (Correct)" || log_warning "  -> Rich Text check failed: answer does not contain HTML"

# 4. Chat streaming (SSE)
log_info "POST /api/chat/stream — Streaming (max 60s)"
QUERY_BODY='{"question": "GPA bao nhiêu thì được tốt nghiệp?", "chatHistory": []}'
RESPONSE_STREAM=$(curl -s -N --max-time 60 -X POST "${API_URL}/chat/stream" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null)

CUR_EXIT=$?
if [ $CUR_EXIT -eq 28 ]; then
    log_error "Chat Stream — Request timed out (60s)"
    return 1
elif [ $CUR_EXIT -ne 0 ]; then
    log_error "Chat Stream — Curl failed with exit code $CUR_EXIT"
    return 1
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

# 5. List Chat Sessions
log_info "GET /api/chat/sessions — Active"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/chat/sessions" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Chat Sessions (Active)"

BODY=$(echo "$RESPONSE" | sed '$d')
SESSION_ID=$(echo "$BODY" | jq -r '.items[0].id // empty')

if [ -n "$SESSION_ID" ] && [ "$SESSION_ID" != "null" ]; then
    log_success "  -> Found session: $SESSION_ID"

    # 6. List Chat Messages
    log_info "GET /api/chat/sessions/${SESSION_ID}/messages"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/chat/sessions/${SESSION_ID}/messages" \
        -H "Content-Type: application/json" \
        -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "List Chat Messages"

    # 7. Archive Session
    log_info "POST /api/chat/sessions/${SESSION_ID}/archive"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/sessions/${SESSION_ID}/archive" \
        -H "Content-Type: application/json" \
        -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Archive Chat Session"

    # 8. Unarchive Session
    log_info "POST /api/chat/sessions/${SESSION_ID}/unarchive"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/sessions/${SESSION_ID}/unarchive" \
        -H "Content-Type: application/json" \
        -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Unarchive Chat Session"

else
    log_warning "  -> No active chat sessions found to test archive/unarchive (this is fine on empty db)"
fi

# 9. List Chat Sessions - with status_filter=active
log_info "GET /api/chat/sessions?status_filter=active"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/chat/sessions?status_filter=active" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Chat Sessions (Status Filter = Active)"

# 10. List Chat Sessions - with status_filter=archived
log_info "GET /api/chat/sessions?status_filter=archived"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/chat/sessions?status_filter=archived" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Chat Sessions (Status Filter = Archived)"

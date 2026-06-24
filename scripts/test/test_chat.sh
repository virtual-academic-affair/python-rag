#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "6. CHAT — Smoke"

log_info "POST /api/chat/query — small talk bypass"
QUERY_BODY='{"question": "Xin chào, bạn là ai?", "chatHistory": []}'
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Chat Query — Small Talk"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.source == "llm"' >/dev/null \
        && log_success "  -> Small talk bypass uses llm source" \
        || { log_error "  -> Small talk source mismatch"; return 1; }
    SESSION_ID=$(echo "$BODY" | jq -r '.sessionId // empty')
fi

log_info "POST /api/chat/query — RAG with rich text and citation options"
QUERY_BODY='{"question": "Quy chế là gì?", "chatHistory": [], "toRichText": true, "resolveCitations": true, "citationLinkType": "markdown"}'
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Chat Query — RAG Customizations"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | grep -q '<p>' \
        && log_success "  -> Rich text answer contains HTML" \
        || { log_error "  -> Rich text answer missing HTML"; return 1; }
    echo "$BODY" | jq -e 'has("sources")' >/dev/null \
        && log_success "  -> Sources field is present" \
        || { log_error "  -> Sources field missing"; return 1; }
fi

log_info "POST /api/chat/stream — streaming (max 180s)"
QUERY_BODY='{"question": "GPA bao nhiêu thì được tốt nghiệp?", "chatHistory": []}'
RESPONSE_STREAM=$(curl -s -N --max-time 180 -X POST "${API_URL}/chat/stream" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null)
CUR_EXIT=$?
if [ $CUR_EXIT -eq 28 ]; then
    log_error "Chat Stream — Request timed out (180s)"
    return 1
elif [ $CUR_EXIT -ne 0 ]; then
    log_error "Chat Stream — Curl failed with exit code $CUR_EXIT"
    return 1
fi
HAS_CHUNK=$(echo "$RESPONSE_STREAM" | grep -Ei '"type":\s*"(text|thought|call)"' | head -n 1 || echo "")
HAS_DONE=$(echo "$RESPONSE_STREAM" | grep -Ei '"done":\s*true' | head -n 1 || echo "")
if [ -n "$HAS_CHUNK" ] && [ -n "$HAS_DONE" ]; then
    log_success "Chat Stream — Received chunks and done signal"
else
    log_error "Chat Stream — Missing valid chunks or done signal"
    log_info "Raw stream sample: ${RESPONSE_STREAM:0:200}..."
    return 1
fi

if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
    log_warning "No sessionId returned from chat query; skipping session archive checks."
    return 0
fi

log_info "GET /api/chat/sessions/${SESSION_ID}/messages"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/chat/sessions/${SESSION_ID}/messages" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Chat Messages"

log_info "POST /api/chat/sessions/${SESSION_ID}/archive"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/sessions/${SESSION_ID}/archive" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Archive Chat Session"

log_info "GET /api/chat/sessions?statusFilter=archived"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/chat/sessions?statusFilter=archived" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "List Chat Sessions — Archived"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg sid "$SESSION_ID" 'all(.items[]?; .status == "archived") and any(.items[]?; .sessionId == $sid)' >/dev/null \
        && log_success "  -> Archived list contains archived session only" \
        || { log_error "  -> Archived list mismatch"; return 1; }
fi

log_info "POST /api/chat/query — archived session auto-unarchives"
QUERY_BODY="{\"sessionId\":\"${SESSION_ID}\",\"question\":\"Xin chào\",\"chatHistory\":[]}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" \
    -d "$QUERY_BODY" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — Archived Session Auto-Unarchive"

log_info "GET /api/chat/sessions?statusFilter=active"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/chat/sessions?statusFilter=active" \
    -H "Content-Type: application/json" \
    -H "${STUDENT_AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "List Chat Sessions — Active"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg sid "$SESSION_ID" 'all(.items[]?; .status == "active") and any(.items[]?; .sessionId == $sid)' >/dev/null \
        && log_success "  -> Active list contains auto-unarchived session only" \
        || { log_error "  -> Active list mismatch"; return 1; }
fi

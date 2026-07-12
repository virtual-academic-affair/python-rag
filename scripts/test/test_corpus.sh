#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "CORPUS — Smoke"

TS=$(date +%s)
ROOT_TOPIC="script-root-${TS}"
CHILD_TOPIC="script-child-${TS}"

cleanup_corpus_smoke() {
    curl -s -X DELETE "${API_URL}/corpus/topics/${CHILD_TOPIC}" -H "${AUTH_HEADER}" >/dev/null 2>&1 || true
    curl -s -X DELETE "${API_URL}/corpus/topics/${ROOT_TOPIC}" -H "${AUTH_HEADER}" >/dev/null 2>&1 || true
}
trap 'cleanup_corpus_smoke; trap - RETURN' RETURN

log_info "GET /api/corpus/stats"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/corpus/stats" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get Corpus Stats"

log_info "POST /api/corpus/topics — create root topic"
ROOT_BODY="{
    \"slug\": \"${ROOT_TOPIC}\",
    \"title\": \"Script Root ${TS}\",
    \"summary\": \"Root topic created by smoke test\"
}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/corpus/topics" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d "$ROOT_BODY" \
    2>/dev/null || echo -e "\n000")
if ! check_response "$RESPONSE" "201" "Create Corpus Root Topic"; then
    return 1
fi
BODY=$(echo "$RESPONSE" | sed '$d')
echo "$BODY" | jq -e --arg key "$ROOT_TOPIC" '.nodeKey == $key and .parentKey == null' >/dev/null \
    && log_success "  -> Root topic response uses camelCase nodeKey/parentKey" \
    || { log_error "  -> Root topic response shape mismatch"; return 1; }

log_info "POST /api/corpus/topics — create child topic"
CHILD_BODY="{
    \"slug\": \"${CHILD_TOPIC}\",
    \"title\": \"Script Child ${TS}\",
    \"summary\": \"Child topic created by smoke test\",
    \"parentKey\": \"${ROOT_TOPIC}\"
}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/corpus/topics" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d "$CHILD_BODY" \
    2>/dev/null || echo -e "\n000")
if ! check_response "$RESPONSE" "201" "Create Corpus Child Topic"; then
    return 1
fi
BODY=$(echo "$RESPONSE" | sed '$d')
echo "$BODY" | jq -e --arg key "$CHILD_TOPIC" --arg parent "$ROOT_TOPIC" '.nodeKey == $key and .parentKey == $parent' >/dev/null \
    && log_success "  -> Child topic linked to parent" \
    || { log_error "  -> Child topic parent mismatch"; return 1; }

log_info "GET /api/corpus/topics/${ROOT_TOPIC} — detail"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/corpus/topics/${ROOT_TOPIC}" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get Corpus Topic"

log_info "GET /api/corpus/topics — list"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/corpus/topics" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "List Corpus Topics"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg key "$ROOT_TOPIC" 'any(.items[]?; .nodeKey == $key)' >/dev/null \
        && log_success "  -> Topic list includes created root" \
        || { log_error "  -> Topic list missing created root"; return 1; }
fi

log_info "GET /api/corpus/tree"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${API_URL}/corpus/tree" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Get Corpus Tree"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e 'has("totalNodes") and has("totalRootNodes") and has("tree")' >/dev/null \
        && log_success "  -> Tree response uses current camelCase fields" \
        || { log_error "  -> Tree response shape mismatch"; return 1; }
fi

log_info "PATCH /api/corpus/topics/${CHILD_TOPIC} — update child"
UPDATE_BODY="{\"title\":\"Script Child Updated ${TS}\",\"summary\":\"Updated by smoke test\"}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/corpus/topics/${CHILD_TOPIC}" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d "$UPDATE_BODY" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Update Corpus Topic"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.title | contains("Updated")' >/dev/null \
        && log_success "  -> Updated topic contains new title" \
        || { log_error "  -> Updated topic missing new title"; return 1; }
fi

log_info "POST /api/corpus/topics/${CHILD_TOPIC}/merge — merge child into root"
MERGE_BODY="{\"targetKey\":\"${ROOT_TOPIC}\"}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/corpus/topics/${CHILD_TOPIC}/merge" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d "$MERGE_BODY" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Merge Corpus Topic"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg from "$CHILD_TOPIC" --arg into "$ROOT_TOPIC" '.mergedFrom == $from and .mergedInto == $into and .sourceDeleted == true' >/dev/null \
        && log_success "  -> Merge response uses current camelCase fields" \
        || { log_error "  -> Merge response shape mismatch"; return 1; }
fi

log_info "POST /api/debug/corpus/traverse — debug traversal contract"
TRAVERSE_BODY='{
    "question": "Điều kiện tốt nghiệp là gì?",
    "role": "lecture",
    "metadataFilter": {
        "academicYear": {"fromYear": 2024, "toYear": 2025}
    }
}'
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/debug/corpus/traverse" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d "$TRAVERSE_BODY" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Debug Corpus Traverse"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.role == "lecture" and has("fileCandidates") and has("faqCandidates") and has("totalFileCandidates") and has("totalFaqCandidates")' >/dev/null \
        && log_success "  -> Traverse response uses typed candidate fields" \
        || { log_error "  -> Traverse response shape mismatch"; return 1; }
fi

log_info "DELETE /api/corpus/topics/${ROOT_TOPIC} — cleanup"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/corpus/topics/${ROOT_TOPIC}" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Delete Corpus Topic"

cleanup_corpus_smoke

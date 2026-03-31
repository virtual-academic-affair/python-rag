#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "3. STORE MANAGEMENT"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create store
log_info "POST /api/stores — Tao store moi (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/stores" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"displayName\": \"Test Store ${TIMESTAMP}\",
        \"setAsDefault\": false
    }" 2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "201" "Create Store"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    STORE_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('storeId',''))" 2>/dev/null || echo "")
    log_info "  -> store_id = $STORE_ID"
    # Export for other scripts if needed, but usually we run them all in one shell session or use shared file
    echo "$STORE_ID" > scripts/test_results/last_store_id.txt
fi

# List stores
log_info "GET /api/stores — Liet ke tat ca"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/stores?page=1&limit=10" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Stores"

# Get default store
log_info "GET /api/stores?isDefault=true — Lay store mac dinh"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/stores?isDefault=true" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Default Store"

# Get store details
if [ -s scripts/test_results/last_store_id.txt ]; then
    STORE_ID=$(cat scripts/test_results/last_store_id.txt)
    log_info "GET /api/stores/${STORE_ID} — Chi tiet store"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/stores/${STORE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Get Store by ID"
    
    log_info "PATCH /api/stores/${STORE_ID} — Cap nhat display_name"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/stores/${STORE_ID}" \
        -H "Content-Type: application/json" \
        -H "${AUTH_HEADER}" \
        -d "{\"displayName\": \"Test Store ${TIMESTAMP} (Updated)\"}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Update Store"
    
    log_info "POST /api/stores/${STORE_ID}/sync — Sync thong ke"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/stores/${STORE_ID}/sync" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Sync Store Stats"
else
    log_skip "Get/Update/Sync Store — bo qua (STORE_ID chua duoc set)"
fi

# Create secondary store to test DELETE
log_info "POST /api/stores — Tao store phu de xoa (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/stores" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"displayName\": \"Temp Store to Delete ${TIMESTAMP}\",
        \"setAsDefault\": false
    }" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "201" "Create Temp Store"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    TEMP_STORE_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('storeId',''))" 2>/dev/null || echo "")
    log_info "  -> temp_store_id = $TEMP_STORE_ID"
    
    log_info "DELETE /api/stores/${TEMP_STORE_ID} — Xoa store"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/stores/${TEMP_STORE_ID}" \
        -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "204" "Delete Store"
fi

# Unauthorized test
log_info "POST /api/stores — khong co token (expect 401)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/stores" \
    -H "Content-Type: application/json" \
    -d '{"displayName": "Unauthorized Store"}' \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "401" "Create Store — no token -> 401"

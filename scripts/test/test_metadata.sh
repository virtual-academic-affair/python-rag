#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "4. METADATA TYPES"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
METADATA_KEY="dept_test_${TIMESTAMP}"

# 1. Create metadata type
log_info "POST /api/metadata — Tao '${METADATA_KEY}' (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/metadata" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d '{
        "key": "'"${METADATA_KEY}"'",
        "displayName": "Phong ban Test",
        "description": "Phong ban phu trach tai lieu",
        "allowedValues": [
            { "value": "dao_tao", "displayName": "Dao tao", "isActive": true, "color": "#3498DB", "visibleRoles": ["lecture", "student"] },
            { "value": "all",     "displayName": "Tat ca",  "isActive": true, "color": "#95A5A6", "visibleRoles": ["lecture", "student"] }
        ]
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "201" "Create Metadata Type"

# 2. Get system metadata
log_info "GET /api/metadata/access_scope — Xac nhan system type"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata/access_scope" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get System Metadata Type"

# 3. List metadata (Default/Admin - should see all)
log_info "GET /api/metadata — Liet ke tat ca (Admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Metadata (Admin)"

# 3.1 Verify Sorting (isSystem=true first)
log_info "Check sorting: isSystem should be first"
FIRST_KEY=$(echo "$RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metadataTypes'][0]['key'])" 2>/dev/null || echo "")
FIRST_IS_SYSTEM=$(echo "$RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['metadataTypes'][0]['isSystem'])" 2>/dev/null || echo "")
log_info "  -> First key: $FIRST_KEY, isSystem: $FIRST_IS_SYSTEM"
if [ "$FIRST_IS_SYSTEM" = "True" ]; then
    log_success "System metadata sorted at top"
else
    log_error "System metadata NOT at top"
fi

# 3.2 Test isActive filtering
log_info "GET /api/metadata?isActive=true — Filter active only"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata?isActive=true" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Active Metadata"
COUNT_ACTIVE=$(echo "$RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['metadataTypes']))" 2>/dev/null || echo "0")
log_info "  -> Active count: $COUNT_ACTIVE"

log_info "GET /api/metadata?isActive=false — Filter inactive only"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata?isActive=false" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Inactive Metadata"
COUNT_INACTIVE=$(echo "$RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['metadataTypes']))" 2>/dev/null || echo "0")
log_info "  -> Inactive count: $COUNT_INACTIVE"

# 3.3 Test Keywords search
log_info "GET /api/metadata?keywords=Dao+tao — Search by value display_name"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata?keywords=Dao+tao" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Search Metadata by keywords"
SEARCH_FOUND=$(echo "$RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(any('Đào tạo' in v['displayName'] for mt in d['metadataTypes'] for v in (mt['allowedValues'] or [])))" 2>/dev/null || echo "False")
log_info "  -> Keyword 'Dao tao' found in values: $SEARCH_FOUND"

# 3.4 Test Student Role Visibility (Hidden Inactive)
log_info "GET /api/metadata — Student Visibility (Inactive should be hidden)"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${STUDENT_AUTH_HEADER}" "${API_URL}/metadata" \
    2>/dev/null || echo -e "\n000")
if [ "$(echo "$RESPONSE" | tail -n1)" = "200" ]; then
    log_success "List Metadata (Student) - HTTP 200"
    HAS_INACTIVE=$(echo "$RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(any(not mt['isActive'] for mt in d['metadataTypes']))" 2>/dev/null || echo "False")
    if [ "$HAS_INACTIVE" = "False" ]; then
        log_success "Student cannot see inactive metadata"
    else
        log_error "Student SEES inactive metadata!"
    fi
    
    # Check inactive value in 'department'
    HAS_INACTIVE_VAL=$(echo "$RESPONSE" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); dept=next((mt for mt in d['metadataTypes'] if mt['key'] == 'department'), None); print(any(not v['isActive'] for v in dept['allowedValues']) if dept else 'False')" 2>/dev/null || echo "False")
    if [ "$HAS_INACTIVE_VAL" = "False" ]; then
        log_success "Student cannot see inactive allowed values"
    else
        log_error "Student SEES inactive allowed values!"
    fi
else
    log_warning "Student request failed (HTTP $(echo "$RESPONSE" | tail -n1)) - Signature might be invalid on remote server"
fi

# 4. Update core
log_info "PATCH /api/metadata/${METADATA_KEY} — Cap nhat core"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/metadata/${METADATA_KEY}" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{ \"displayName\": \"Phong ban Updated ${TIMESTAMP}\" }" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Update Metadata Type Core"

# 5. Add value
VAL_KEY="val_${TIMESTAMP}"
log_info "POST /api/metadata/${METADATA_KEY}/values — Them gia tri ${VAL_KEY}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/metadata/${METADATA_KEY}/values" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{ \"value\": \"${VAL_KEY}\", \"displayName\": \"Test Val\", \"isActive\": true, \"color\": \"#9B59B6\", \"visibleRoles\": [\"student\"] }" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Add Metadata Value"

log_info "GET /api/metadata/exists?key=${METADATA_KEY} — Kiem tra ton tai"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata/exists?key=${METADATA_KEY}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Check Metadata Exists"

log_info "PATCH /api/metadata/${METADATA_KEY}/values/${VAL_KEY} — Cap nhat gia tri"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/metadata/${METADATA_KEY}/values/${VAL_KEY}" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{ \"displayName\": \"Updated Val\", \"isActive\": false }" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Update Metadata Value"

log_info "DELETE /api/metadata/${METADATA_KEY}/values/${VAL_KEY} — Xoa gia tri"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/metadata/${METADATA_KEY}/values/${VAL_KEY}" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Delete Metadata Value"

# 6. Delete metadata (cleanup)
log_info "DELETE /api/metadata/${METADATA_KEY} — Hard Delete"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/metadata/${METADATA_KEY}" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Hard Delete Metadata Type"

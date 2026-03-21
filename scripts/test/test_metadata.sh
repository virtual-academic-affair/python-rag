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
            { "value": "dao_tao", "displayName": "Dao tao", "isActive": true, "color": "#3498DB", "visibleRoles": ["admin", "lecture", "student"] },
            { "value": "all",     "displayName": "Tat ca",  "isActive": true, "color": "#95A5A6", "visibleRoles": ["admin", "lecture", "student"] }
        ]
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "201" "Create Metadata Type"

# 2. Get system metadata
log_info "GET /api/metadata/access_scope — Xac nhan system type"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata/access_scope" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get System Metadata Type"

# 3. List metadata
log_info "GET /api/metadata — Liet ke tat ca"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Metadata Types"

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
    -d "{ \"value\": \"${VAL_KEY}\", \"displayName\": \"Test Val\", \"isActive\": true, \"color\": \"#9B59B6\", \"visibleRoles\": [\"admin\", \"student\"] }" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Add Metadata Value"

# 6. Delete metadata (cleanup)
log_info "DELETE /api/metadata/${METADATA_KEY} — Hard Delete"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/metadata/${METADATA_KEY}" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Hard Delete Metadata Type"

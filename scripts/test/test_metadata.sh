#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "4. METADATA SCHEMA"

# 1. Get metadata schema
log_info "GET /api/metadata/schema — Get fixed schema definition"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata/schema" \
    2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "200" "Get Metadata Schema"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    log_info "Response Body:"
    echo "$BODY" | jq .
    
    # Verify presence of documentTypes
    HAS_TYPES=$(echo "$BODY" | jq -r '.documentTypes | length > 0')
    if [ "$HAS_TYPES" = "true" ]; then
        log_success "Found document types in schema"
    else
        log_error "No document types found in schema"
    fi
    
    # Verify year ranges
    MIN_Y=$(echo "$BODY" | jq -r '.yearMin')
    MAX_Y=$(echo "$BODY" | jq -r '.yearMax')
    log_info "  -> Year range: $MIN_Y to $MAX_Y"
    if [ "$MIN_Y" = "0" ] && [ "$MAX_Y" = "9999" ]; then
        log_success "Year range sentinels are correct"
    else
        log_warning "Year range sentinels differ from expected (0-9999)"
    fi
fi

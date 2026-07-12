#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "FORMS — Smoke"

TS=$(date +%s)
FORMS_SAMPLE_FILE="$REPO_ROOT/scripts/test/sample_forms_${TS}.csv"
cleanup_forms_smoke() {
    rm -f "$FORMS_SAMPLE_FILE" "$REPO_ROOT/scripts/test/sample_forms.csv"
}
trap 'cleanup_forms_smoke; trap - RETURN' RETURN

log_info "POST /api/forms/import-preview — CSV preview"
cat << EOF > "$FORMS_SAMPLE_FILE"
STT,Loại văn bản,Liên kết,Năm học,Khóa,Ghi chú
1,"Biểu mẫu CSV 1 (${TS})","https://example.com/csv1","2024-2025","","Ghi chú CSV 1"
2,"","https://example.com/csv2","","",""
EOF

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms/import-preview" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@${FORMS_SAMPLE_FILE}" \
    -F "document_type_col=Loại văn bản" \
    -F "content_link_col=Liên kết" \
    -F "notes_col=Ghi chú" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Preview Forms Import"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.totalPreviewed == 1' >/dev/null \
        && log_success "  -> Preview includes only valid form row" \
        || { log_error "  -> Preview valid row count mismatch"; return 1; }
fi

log_info "POST /api/forms/import — CSV import"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms/import" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@${FORMS_SAMPLE_FILE}" \
    -F "document_type_col=Loại văn bản" \
    -F "content_link_col=Liên kết" \
    -F "notes_col=Ghi chú" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Import Forms"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.count == 1' >/dev/null \
        && log_success "  -> Import created one valid form" \
        || { log_error "  -> Import count mismatch"; return 1; }
fi

log_info "POST /api/forms/import-preview — invalid start_row"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms/import-preview" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@${FORMS_SAMPLE_FILE}" \
    -F "start_row=abc" \
    -F "document_type_col=Loại văn bản" \
    -F "content_link_col=Liên kết" \
    -F "notes_col=Ghi chú" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "400" "Reject invalid Forms import start_row"

log_info "POST /api/forms — create"
CREATE_JSON="{\"documentType\":\"Biểu mẫu xin nghỉ phép (${TS})\",\"contentLink\":\"https://example.com\",\"notes\":\"Ghi chú\"}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$CREATE_JSON" \
    2>/dev/null || echo -e "\n000")
if ! check_response "$RESPONSE" "201" "Create Form"; then
    return 1
fi
BODY=$(echo "$RESPONSE" | sed '$d')
FORM_ID=$(echo "$BODY" | jq -r '.id // empty')
log_info "  -> form_id = $FORM_ID"

log_info "GET /api/forms — search and verify created form"
RESPONSE=$(curl -s -w "\n%{http_code}" -G "${BASE_URL}/api/forms" \
    --data-urlencode "search=${TS}" \
    --data-urlencode "limit=5" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Search Forms"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e --arg id "$FORM_ID" 'any(.items[]?; .id == $id)' >/dev/null \
        && log_success "  -> Form search includes created form" \
        || { log_error "  -> Form search missing created form"; return 1; }
fi

log_info "PUT /api/forms/${FORM_ID} — update"
UPDATE_JSON="{\"documentType\":\"Biểu mẫu xin nghỉ phép Updated (${TS})\",\"contentLink\":\"https://example.com/updated\"}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT "${BASE_URL}/api/forms/${FORM_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$UPDATE_JSON" \
    2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "200" "Update Form"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    echo "$BODY" | jq -e '.documentType | contains("Updated")' >/dev/null \
        && log_success "  -> Updated form contains new document type" \
        || { log_error "  -> Updated form missing new document type"; return 1; }
fi

log_info "GET /api/forms/${FORM_ID} — detail"
RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/forms/${FORM_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get Form"

log_info "DELETE /api/forms/${FORM_ID} — cleanup"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${BASE_URL}/api/forms/${FORM_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Delete Form"

cleanup_forms_smoke

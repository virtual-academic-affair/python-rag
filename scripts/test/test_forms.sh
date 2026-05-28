#!/bin/bash
# Test script for Forms Module

# Include common utilities
source "$(dirname "$0")/common.sh"

echo "=========================================="
echo "          Testing Forms Module            "
echo "=========================================="

# 1. Test List Forms (Empty initially or may have existing)
echo -e "\n1. Test List Forms"
response=$(curl -s -w "\n%{http_code}" -G "${BASE_URL}/api/forms" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")
    
HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .

if [ "$HTTP_CODE" -lt 400 ]; then
    echo "✅ List Forms successful"
else
    echo "❌ Failed to list Forms"
    exit 1
fi

TS=$(date +%s)

# 2. Test Excel Import Preview
echo -e "\n2. Test Excel Import Preview for Forms"
# Create a fresh unique Excel file
python3 -c "
import openpyxl
import time
from openpyxl.styles import Font

ts = int(time.time())
wb = openpyxl.Workbook()
ws = wb.active
ws.append(['STT', 'Loại văn bản', 'Liên kết', 'Năm học', 'Khóa', 'Ghi chú'])

# Row 1: Valid form
ws.append([1, f'Biểu mẫu xin nghỉ học ({ts})', 'https://example.com/form1', '2024-2025', '', 'Ghi chú 1'])

# Row 2: Invalid form (missing type)
ws.append([2, '', 'https://example.com/form2', '', '', ''])

wb.save('scripts/test/sample_forms.xlsx')
"

response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms/import-preview" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_forms.xlsx" \
    -F "document_type_col=Loại văn bản" \
    -F "content_link_col=Liên kết" \
    -F "notes_col=Ghi chú" \
    -F "metadataFilterJson={\"academicYear\": \"Năm học\", \"enrollmentYear\": \"Khóa\"}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
TOTAL_ROWS=$(echo "$BODY" | jq -r '.totalPreviewed // empty')
if [ "$TOTAL_ROWS" -eq 1 ]; then
    echo "✅ Excel forms import preview successful (Found 1 valid row)"
else
    echo "❌ Failed Excel forms import preview (Expected 1 valid row, found $TOTAL_ROWS)"
fi

# 3. Test Excel Import (Actual)
echo -e "\n3. Test Excel Import (Actual) for Forms"
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms/import" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_forms.xlsx" \
    -F "document_type_col=Loại văn bản" \
    -F "content_link_col=Liên kết" \
    -F "notes_col=Ghi chú" \
    -F "metadataFilterJson={\"academicYear\": \"Năm học\", \"enrollmentYear\": \"Khóa\"}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
IMPORT_COUNT=$(echo "$BODY" | jq -r '.count // empty')
if [ "$IMPORT_COUNT" -eq 1 ]; then
    echo "✅ Excel forms bulk import successful (1 created/updated)"
else
    echo "❌ Failed Excel forms bulk import (Expected 1, found $IMPORT_COUNT)"
fi

# 4. Test CSV Import Preview for Forms
echo -e "\n4. Test CSV Import Preview for Forms"
cat << EOF > scripts/test/sample_forms.csv
STT,Loại văn bản,Liên kết,Năm học,Khóa,Ghi chú
1,"Biểu mẫu CSV 1 ($TS)","https://example.com/csv1","2024-2025","","Ghi chú CSV 1"
2,"","https://example.com/csv2","","",""
EOF

response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms/import-preview" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_forms.csv" \
    -F "document_type_col=Loại văn bản" \
    -F "content_link_col=Liên kết" \
    -F "notes_col=Ghi chú" \
    -F "metadataFilterJson={\"academicYear\": \"Năm học\", \"enrollmentYear\": \"Khóa\"}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
TOTAL_ROWS=$(echo "$BODY" | jq -r '.totalPreviewed // empty')
if [ "$TOTAL_ROWS" -eq 1 ]; then
    echo "✅ CSV forms import preview successful (Found 1 valid row)"
else
    echo "❌ Failed CSV forms import preview (Expected 1 valid row, found $TOTAL_ROWS)"
fi

# 5. Test CSV Import (Actual) for Forms
echo -e "\n5. Test CSV Import (Actual) for Forms"
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms/import" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_forms.csv" \
    -F "document_type_col=Loại văn bản" \
    -F "content_link_col=Liên kết" \
    -F "notes_col=Ghi chú" \
    -F "metadataFilterJson={\"academicYear\": \"Năm học\", \"enrollmentYear\": \"Khóa\"}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
IMPORT_COUNT=$(echo "$BODY" | jq -r '.count // empty')
if [ "$IMPORT_COUNT" -eq 1 ]; then
    echo "✅ CSV forms bulk import successful (1 created/updated)"
else
    echo "❌ Failed CSV forms bulk import (Expected 1, found $IMPORT_COUNT)"
fi

# 6. Test Create Form
echo -e "\n6. Test Create Form"
BODY_JSON="{\"documentType\": \"Biểu mẫu xin nghỉ phép ($TS)\", \"contentLink\": \"https://example.com\", \"notes\": \"Ghi chú\"}"
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/forms" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$BODY_JSON")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
FORM_ID=$(echo "$BODY" | jq -r '.id // empty')
if [ -n "$FORM_ID" ] && [ "$FORM_ID" != "null" ]; then
    echo "✅ Create Form successful (ID: $FORM_ID)"
else
    echo "❌ Failed to create form"
    exit 1
fi

# 7. Test Get Form
echo -e "\n7. Test Get Form"
response=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/forms/${FORM_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")
HTTP_CODE=$(echo "$response" | tail -n1)
if [ "$HTTP_CODE" -eq 200 ]; then
    echo "✅ Get Form successful"
else
    echo "❌ Failed to get form"
fi

# 8. Test Update Form
echo -e "\n8. Test Update Form"
UPDATE_JSON="{\"documentType\": \"Biểu mẫu xin nghỉ phép (Updated)\", \"contentLink\": \"https://example.com/updated\"}"
response=$(curl -s -w "\n%{http_code}" -X PUT "${BASE_URL}/api/forms/${FORM_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$UPDATE_JSON")
HTTP_CODE=$(echo "$response" | tail -n1)
if [ "$HTTP_CODE" -eq 200 ]; then
    echo "✅ Update Form successful"
else
    echo "❌ Failed to update form"
fi

# 9. Test Delete Form
echo -e "\n9. Test Delete Form"
response=$(curl -s -w "\n%{http_code}" -X DELETE "${BASE_URL}/api/forms/${FORM_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")
HTTP_CODE=$(echo "$response" | tail -n1)
if [ "$HTTP_CODE" -eq 204 ] || [ "$HTTP_CODE" -eq 200 ]; then
    echo "✅ Delete Form successful"
else
    echo "❌ Failed to delete form"
fi
echo -e "
🎉 All Forms tests completed!"

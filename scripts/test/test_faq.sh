#!/bin/bash
# Test script for FAQ Module v2

# Include common utilities
source "$(dirname "$0")/common.sh"

echo "=========================================="
echo "          Testing FAQ Module              "
echo "=========================================="

# 1. Test Create FAQ
echo -e "\n1. Test Create FAQ"
FAQ_DATA='{
    "question": "Làm thế nào để đăng ký giấy chứng nhận sinh viên?",
    "answerRichText": "<p>Bạn có thể đăng ký trực tuyến trên cổng thông tin sinh viên hoặc đến trực tiếp Phòng Giáo vụ.</p>",
    "metadataFilter": {
        "academicYear": ["2023-2024", "2024-2025"],
        "cohort": []
    }
}'

response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${FAQ_DATA}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .

FAQ_ID=$(echo "$BODY" | jq -r '.id // .faqId')

if [ "$FAQ_ID" == "null" ] || [ -z "$FAQ_ID" ] || [ "$HTTP_CODE" -ge 400 ]; then
    echo "❌ Failed to create FAQ"
    exit 1
else
    echo "✅ Created FAQ with ID: $FAQ_ID"
fi


# 2. Test List FAQs
echo -e "\n2. Test List FAQs"
FILTER_JSON='{"academicYear":["2023-2024"]}'
response=$(curl -s -w "\n%{http_code}" -G "${BASE_URL}/api/faqs" \
    --data-urlencode "metadataFilter=${FILTER_JSON}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")
    
HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
COUNT=$(echo "$BODY" | jq -r '.total')

if [ "$COUNT" -gt 0 ]; then
    echo "✅ List FAQs successful, found $COUNT items"
else
    echo "❌ Failed to list FAQs"
fi

# 2.1 Test Full Text Search (New)
echo -e "\n2.1 Test Full Text Search (Keyword: 'giấy chứng nhận')"
response=$(curl -s -w "\n%{http_code}" -G "${BASE_URL}/api/faqs" \
    --data-urlencode "search=giấy chứng nhận" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
FTS_COUNT=$(echo "$BODY" | jq -r '.total')
if [ "$FTS_COUNT" -gt 0 ]; then
    echo "✅ Full Text Search successful, found $FTS_COUNT items"
else
    echo "❌ Full Text Search failed (Keyword: 'giấy chứng nhận')"
fi


# 2.5 Test Get FAQ
echo -e "\n2.5 Test Get FAQ"
response=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
CHECK_ID=$(echo "$BODY" | jq -r '.id // .faqId')
if [ "$CHECK_ID" == "$FAQ_ID" ]; then
    echo "✅ Get FAQ successful"
else
    echo "❌ Failed to get FAQ"
fi

# 2.6 Test Update FAQ
echo -e "\n2.6 Test Update FAQ"
UPDATE_DATA='{
    "question": "Làm thế nào để đăng ký giấy chứng nhận sinh viên (updated)?",
    "answerRichText": "<p>Bạn có thể đăng ký trực tuyến trên cổng thông tin sinh viên.</p>"
}'
response=$(curl -s -w "\n%{http_code}" -X PATCH "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${UPDATE_DATA}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
UPDATED_QUESTION=$(echo "$BODY" | jq -r '.question')
if [[ "$UPDATED_QUESTION" == *"updated"* ]]; then
    echo "✅ Update FAQ successful"
else
    echo "❌ Failed to update FAQ"
fi


# 3. Test Match FAQ (Semantic Search Debug)
echo -e "\n3. Test Match FAQ (Semantic Search)"
MATCH_DATA='{
    "question": "Làm thế nào để đăng ký giấy chứng nhận sinh viên?",
    "threshold": 0.85,
    "metadataFilter": {
        "academicYear": ["2024-2025"],
        "cohort": ["K20"]
    }
}'

response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/match" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${MATCH_DATA}")
    
HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
MATCHED_ID=$(echo "$BODY" | jq -r '.id // .faqId')

if [ "$MATCHED_ID" == "$FAQ_ID" ]; then
    echo "✅ Semantic match successful"
else
    echo "⚠️ Semantic match might have failed or found a different FAQ. Check threshold."
fi

# 4. Test Synthesis Trigger
echo -e "\n4. Test Synthesis Trigger"
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/synthesis" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{}')
    
HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
BATCH_ID=$(echo "$BODY" | jq -r '.batchId')

if [ "$BATCH_ID" != "null" ] && [ -n "$BATCH_ID" ]; then
    echo "✅ Synthesis triggered successfully, Batch ID: $BATCH_ID"
else
    echo "❌ Failed to trigger synthesis"
fi


# 4.5 Test List Candidates
echo -e "\n4.5 Test List Candidates"
response=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/faqs/candidates/list?status=pending" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
CANDIDATE_ID=$(echo "$BODY" | jq -r '.items[0].id // .items[0].candidateId // empty')

if [ -n "$CANDIDATE_ID" ] && [ "$CANDIDATE_ID" != "null" ]; then
    echo "✅ List Candidates successful, found candidate: $CANDIDATE_ID"
    
    # 4.6 Test Get Candidate
    echo -e "\n4.6 Test Get Candidate"
    response=$(curl -s -w "\n%{http_code}" -X GET "${BASE_URL}/api/faqs/candidates/${CANDIDATE_ID}" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}")

    HTTP_CODE=$(echo "$response" | tail -n1)
    BODY=$(echo "$response" | sed '$d')

    echo "Status: $HTTP_CODE"
    echo "Response:"
echo "$BODY" | jq .
    CHECK_CID=$(echo "$BODY" | jq -r '.id // .candidateId')
    if [ "$CHECK_CID" == "$CANDIDATE_ID" ]; then
        echo "✅ Get Candidate successful"
    else
        echo "❌ Failed to get Candidate"
    fi
    
    # 4.7 Test Review Candidate
    echo -e "\n4.7 Test Review Candidate"
    REVIEW_DATA='{
        "action": "approve",
        "questionOverride": "Tôi muốn xin bảng điểm bằng tiếng Anh thì làm thế nào? (Approved)",
        "answerRichTextOverride": "<p>Bạn có thể đăng ký cấp bảng điểm tiếng Anh qua cổng thông tin sinh viên.</p>",
        "metadataFilterOverride": {
            "academicYear": [],
            "cohort": []
        },
        "note": "Looks good"
    }'
    response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/candidates/${CANDIDATE_ID}/review" \
        -H "Authorization: Bearer ${ADMIN_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "${REVIEW_DATA}")

    HTTP_CODE=$(echo "$response" | tail -n1)
    BODY=$(echo "$response" | sed '$d')

    echo "Status: $HTTP_CODE"
    echo "Response:"
echo "$BODY" | jq .
    # Action 'approve' creates a new FAQ and returns it. Or if it returns status, let's check output.
    # The response is typically the Candidate object updated, or success message.
    # We will just check if HTTP error
    if [[ "$HTTP_CODE" -lt 400 ]]; then
        echo "✅ Review Candidate successful"
    else
        echo "❌ Failed to review Candidate"
    fi
else
    echo "⚠️ List Candidates successful but no candidates found to test Get/Review."
fi


# 4.8 Test Bulk FAQ (JSON)
echo -e "\n4.8 Test Bulk FAQ (JSON)"
TS=$(date +%s)
BULK_DATA="{
    \"items\": [
        {
            \"question\": \"Làm sao để biết mình đã đủ tín chỉ ra trường? ($TS)\",
            \"answerRichText\": \"<p>Bạn có thể kiểm tra tiến độ học tập trên trang cá nhân của mình.</p>\",
            \"metadataFilter\": {\"academicYear\": [\"2024-2025\"], \"cohort\": [\"k19\"]}
        },
        {
            \"question\": \"Trường có hỗ trợ vay vốn sinh viên không? ($TS)\",
            \"answerRichText\": \"<p>Có, bạn liên hệ Phòng Công tác sinh viên để được hướng dẫn thủ tục vay vốn.</p>\",
            \"metadataFilter\": {\"academicYear\": [\"all\"], \"cohort\": [\"all\"]}
        }
    ],
    \"skipDuplicates\": true
}"
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/bulk" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${BULK_DATA}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
CREATED_COUNT=$(echo "$BODY" | jq -r '.created')
if [ "$CREATED_COUNT" -eq 2 ]; then
    echo "✅ Bulk create JSON successful"
else
    echo "❌ Failed bulk create JSON"
fi

# 4.9 Test Excel Import Preview
echo -e "\n4.9 Test Excel Import Preview"
# Create a fresh unique Excel file
python3 -c "
import openpyxl
import time
from openpyxl.styles import Font

ts = int(time.time())
wb = openpyxl.Workbook()
ws = wb.active
ws.append(['STT', 'Câu hỏi', 'Trả lời', 'Năm học', 'Khóa'])

# Row 1: Plain text
ws.append([1, f'Học phí năm học 2024 là bao nhiêu? ({ts})', 'Học phí là 30 triệu/năm.', '2024-2025', 'all'])

# Row 2: Bold Answer (Full cell)
ws.cell(row=3, column=1, value=2)
ws.cell(row=3, column=2, value=f'Làm thế nào để đăng ký học phần? ({ts})')
cell_a2 = ws.cell(row=3, column=3, value='Bạn vào trang portal để đăng ký.')
cell_a2.font = Font(bold=True)
ws.cell(row=3, column=4, value='all')
ws.cell(row=3, column=5, value='k18,k19')

# Row 3: Simple HTML-like text
ws.cell(row=4, column=1, value=3)
ws.cell(row=4, column=2, value=f'Link đăng ký ở đâu? ({ts})')
ws.cell(row=4, column=3, value='Vui lòng truy cập <b>Cổng thông tin</b> hoặc xem <i>hướng dẫn</i>.')
ws.cell(row=4, column=4, value='all')
ws.cell(row=4, column=5, value='all')

# Row 4: Short question (Fail case)
ws.append([4, 'Q', 'Short', 'all', 'all']) 

wb.save('scripts/test/sample_bulk_faq_unique.xlsx')
"

response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/import/preview" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_bulk_faq_unique.xlsx" \
    -F "question_col=Câu hỏi" \
    -F "answer_col=Trả lời" \
    -F "metadataFilterJson={\"academic_year\": \"Năm học\", \"cohort\": \"Khóa\"}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
TOTAL_ROWS=$(echo "$BODY" | jq -r '.totalRows')
if [ "$TOTAL_ROWS" -eq 4 ]; then
    echo "✅ Excel import preview successful (Found 4 rows)"
else
    echo "❌ Failed Excel import preview (Expected 4 rows, found $TOTAL_ROWS)"
fi

# 4.10 Test Excel Import (Actual)
echo -e "\n4.10 Test Excel Import (Actual)"
response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/import" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -F "file=@scripts/test/sample_bulk_faq_unique.xlsx" \
    -F "question_col=Câu hỏi" \
    -F "answer_col=Trả lời" \
    -F "metadataFilterJson={\"academic_year\": \"Năm học\", \"cohort\": \"Khóa\"}")

HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
IMPORT_CREATED=$(echo "$BODY" | jq -r '.created')
IMPORT_FAILED=$(echo "$BODY" | jq -r '.failed')
# Row 4 (short question) should fail, Row 1, 2, 3 should succeed
if [ "$IMPORT_CREATED" -eq 3 ] && [ "$IMPORT_FAILED" -eq 1 ]; then
    echo "✅ Excel bulk import successful (3 created, 1 failed as expected)"
else
    echo "❌ Failed Excel bulk import (Created: $IMPORT_CREATED, Failed: $IMPORT_FAILED)"
fi


# 5. Clean up
echo -e "\n5. Clean up - Delete FAQ"
response=$(curl -s -X DELETE "${BASE_URL}/api/faqs/${FAQ_ID}" \
    -w "%{http_code}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}")
    
if [[ "$response" == *"204"* ]]; then
    echo "✅ FAQ deleted successfully"
else
    echo "❌ Failed to delete FAQ, code: $response"
fi

# 6. Test Match against Seeded FAQ
echo -e "\n6. Test Match against Seeded FAQ (requires running seed_faqs.py first)"
SEEDED_MATCH_DATA='{
    "question": "Muốn bảo lưu học tập thì phải làm sao đây?",
    "threshold": 0.85
}'

response=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/api/faqs/match" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${SEEDED_MATCH_DATA}")
    
HTTP_CODE=$(echo "$response" | tail -n1)
BODY=$(echo "$response" | sed '$d')

echo "Status: $HTTP_CODE"
echo "Response:"
echo "$BODY" | jq .
SEEDED_MATCHED_ID=$(echo "$BODY" | jq -r '.id // .faqId // empty')

if [ -n "$SEEDED_MATCHED_ID" ] && [ "$SEEDED_MATCHED_ID" != "null" ]; then
    echo "✅ Semantic match with seeded data successful (Matched ID: $SEEDED_MATCHED_ID)"
else
    echo "⚠️ Seeded semantic match failed. (Is the seed data loaded?)"
fi

echo -e "\n🎉 All FAQ tests completed!"

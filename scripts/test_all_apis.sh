#!/bin/bash

# ==============================================================================
# AI Service API Test Script v3.0.0
# Test tất cả APIs: Health, Classification, Auth, Stores, Metadata, Files, Chat
# ==============================================================================

# Configuration
BASE_URL="${AI_SERVICE_URL:-http://localhost:8000}"
API_URL="${BASE_URL}/api"

# JWT Token (admin role) — thay đổi nếu cần
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOjEsImVtYWlsIjoiYmx1ZWxvb3AudXNAZ21haWwuY29tIiwicm9sZSI6ImFkbWluIiwiaWF0IjoxNzcxOTEzOTgzLCJleHAiOjM3NzcxOTEzOTgzLCJhdWQiOiJ2YWEtYXVkIiwiaXNzIjoidmFhLWlzcyJ9.RtRCZsru6KuCkHUt06cr0v31z9SG0lWWdOORTo47-j4"
AUTH_HEADER="Authorization: Bearer ${TOKEN}"
TIMESTAMP=$(date +%s)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Counters
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# Shared state
STORE_ID=""
FILE_ID=""
FILE_ID_2=""
METADATA_KEY="department"

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[PASS]${NC} $1"; TESTS_PASSED=$((TESTS_PASSED + 1)); }
log_error()   { echo -e "${RED}[FAIL]${NC} $1"; TESTS_FAILED=$((TESTS_FAILED + 1)); }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_skip()    { echo -e "${CYAN}[SKIP]${NC} $1"; TESTS_SKIPPED=$((TESTS_SKIPPED + 1)); }
log_header()  {
    echo ""
    echo -e "${YELLOW}════════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}  $1${NC}"
    echo -e "${YELLOW}════════════════════════════════════════════════════════════${NC}"
}

check_response() {
    local response="$1"
    local expected_code="$2"
    local test_name="$3"

    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "$expected_code" ]; then
        log_success "$test_name (HTTP $http_code)"
        echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
        return 0
    else
        log_error "$test_name — Expected $expected_code, got $http_code"
        echo "$body"
        return 1
    fi
}

create_test_files() {
    local dir="scripts/uploads"
    mkdir -p "$dir"

    cat > "${dir}/test_document.txt" << 'EOF'
# Quy che dao tao Dai hoc

## Chuong 1: Quy dinh chung

### Dieu 1: Pham vi ap dung
Quy che nay ap dung cho tat ca sinh vien he chinh quy cua truong.

### Dieu 2: Thoi gian dao tao
- Thoi gian dao tao chuan: 4 nam (8 hoc ky)
- Thoi gian toi da: 6 nam

### Dieu 3: Dieu kien tot nghiep
1. Hoan thanh tat ca cac hoc phan trong chuong trinh dao tao
2. Diem trung binh tich luy >= 2.0
3. Khong con hoc phan bi diem F
4. Dat chuan dau ra ngoai ngu (TOEIC 450 hoac tuong duong)

## Chuong 2: Dang ky hoc phan

### Dieu 4: Thoi gian dang ky
- Dang ky chinh: 2 tuan truoc khi bat dau hoc ky
- Dang ky bo sung: Tuan dau tien cua hoc ky

### Dieu 5: So tin chi
- Toi thieu: 14 tin chi/hoc ky
- Toi da: 25 tin chi/hoc ky

---
Cap nhat: 2026 | Phong Dao tao
EOF

    cat > "${dir}/test_document_2.txt" << 'EOF'
# Quy dinh hoc bong khuyen khich hoc tap

## Dieu 1: Doi tuong
Sinh vien he chinh quy dat ket qua hoc tap xuat sac.

## Dieu 2: Muc hoc bong
- Loai xuat sac (GPA >= 3.6): 100% hoc phi
- Loai gioi (GPA 3.2-3.59): 80% hoc phi
- Loai kha (GPA 2.5-3.19): 50% hoc phi

## Dieu 3: Dieu kien xet
- Khong co hoc phan F trong hoc ky xet
- Dang ky du so tin chi toi thieu

---
Cap nhat: 2026 | Phong Dao tao
EOF

    log_info "Da tao file test tai: $dir/"
}

# ==============================================================================
# 1. HEALTH CHECK
# ==============================================================================
log_header "1. HEALTH CHECK"

log_info "GET /health"
RESPONSE=$(curl -s -w "\n%{http_code}" "${BASE_URL}/health" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Health check" || {
    log_error "Service khong phan hoi tai ${BASE_URL}. Dung test."
    exit 1
}

log_info "GET / — Root API"
RESPONSE=$(curl -s -w "\n%{http_code}" "${BASE_URL}/" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Root API endpoint"

# ==============================================================================
# 2. EMAIL CLASSIFICATION
# ==============================================================================
log_header "2. EMAIL CLASSIFICATION"

log_info "POST /process — label: classRegistration"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Xin dang ky mon hoc",
        "content": "Em muon dang ky mon Toan cao cap, ma mon MATH101, lop L01. Em la sinh vien nam 2, ma SV001, ten Nguyen Van A."
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — classRegistration"

log_info "POST /process — label: inquiry (AI draft reply)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Hoi ve dieu kien tot nghiep",
        "content": "Em muon hoi dieu kien de tot nghiep cua truong gom nhung gi? Em can bao nhieu tin chi va GPA toi thieu la bao nhieu?"
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — inquiry"

log_info "POST /process — label: task"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Yeu cau cap nhat diem hoc phan",
        "content": "Kinh gui phong dao tao, toi can phong cap nhat diem hoc phan Vat ly dai cuong cho sinh vien SV002 vi co sai sot trong he thong."
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — task"

log_info "POST /process — label: other"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${BASE_URL}/process" \
    -H "Content-Type: application/json" \
    -d '{
        "title": "Thong bao lich thi",
        "content": "Thong bao lich thi hoc ky II nam 2025-2026. Thi bat dau tu ngay 15/3/2026."
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Classify email — other"

log_info "POST /api/test/classification/ingested — Simulate RabbitMQ ingest message"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/test/classification/ingested" \
    -H "Content-Type: application/json" \
    -d '{
        "pattern": "ingested",
        "data": {
            "messageId": 999,
            "subject": "Xin hoi ve lich hoc",
            "senderEmail": "student@example.com",
            "senderName": "Tran Thi B",
            "content": "Cho em hoi lich hoc mon Vat ly tuan toi nhu the nao?"
        }
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Test RabbitMQ ingested message"

# ==============================================================================
# 3. STORE MANAGEMENT
# ==============================================================================
log_header "3. STORE MANAGEMENT"

# 4.1 Tao store
log_info "POST /api/stores — Tao store moi (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/stores" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"display_name\": \"Test Store ${TIMESTAMP}\",
        \"set_as_default\": true
    }" 2>/dev/null || echo -e "\n000")

if check_response "$RESPONSE" "201" "Create Store"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    STORE_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('store_id',''))" 2>/dev/null || echo "")
    log_info "  -> store_id = $STORE_ID"
fi

# 4.2 Liet ke stores
log_info "GET /api/stores — Liet ke tat ca"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/stores?page=1&limit=10" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Stores"

# 4.3 Loc store mac dinh
log_info "GET /api/stores?is_default=true — Lay store mac dinh"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/stores?is_default=true" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Default Store"

# 4.4 Chi tiet store
if [ -n "$STORE_ID" ]; then
    log_info "GET /api/stores/${STORE_ID} — Chi tiet store"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/stores/${STORE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Get Store by ID"
else
    log_skip "Get Store by ID — bo qua (STORE_ID chua duoc set)"
fi

# 4.5 Cap nhat store
if [ -n "$STORE_ID" ]; then
    log_info "PATCH /api/stores/${STORE_ID} — Cap nhat display_name (require_admin)"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/stores/${STORE_ID}" \
        -H "Content-Type: application/json" \
        -H "${AUTH_HEADER}" \
        -d "{\"display_name\": \"Test Store ${TIMESTAMP} (Updated)\"}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Update Store"
else
    log_skip "Update Store — bo qua (STORE_ID chua duoc set)"
fi

# 4.7 Sync thong ke
if [ -n "$STORE_ID" ]; then
    log_info "POST /api/stores/${STORE_ID}/sync — Sync thong ke"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/stores/${STORE_ID}/sync" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Sync Store Stats"
else
    log_skip "Sync Store Stats — bo qua (STORE_ID chua duoc set)"
fi

# 4.8 Error case: khong co token (expect 401)
log_info "POST /api/stores — khong co token (expect 401)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/stores" \
    -H "Content-Type: application/json" \
    -d '{"display_name": "Unauthorized Store"}' \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "401" "Create Store — no token -> 401"

# 4.9 Delete all stores (Dangerous - skip by default)
log_info "DELETE /api/stores/all — Delete all stores (require_admin) — SKIPPED by default"
# RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/stores/all" -H "${AUTH_HEADER}" 2>/dev/null)
# check_response "$RESPONSE" "200" "Delete All Stores"

# ==============================================================================
# 4. METADATA TYPES
# ==============================================================================
log_header "4. METADATA TYPES"

# 5.0 Xoa metadata type cu neu ton tai (de test idempotent)
for KEY in department; do
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${API_URL}/metadata/${KEY}" \
        -H "${AUTH_HEADER}" 2>/dev/null || echo "000")
    if [ "$HTTP" = "204" ]; then
        log_info "Da xoa metadata type ton tai: $KEY (de tao lai)"
    fi
done

# 5.1 Tao metadata type: department
log_info "POST /api/metadata — Tao 'department' (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/metadata" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d '{
        "key": "department",
        "displayName": "Phong ban",
        "description": "Phong ban phu trach tai lieu",
        "allowedValues": [
            { "value": "dao_tao", "displayName": "Dao tao", "isActive": true, "color": "#3498DB" },
            { "value": "khcn",    "displayName": "KHCN",    "isActive": true, "color": "#2ECC71" },
            { "value": "ctsv",    "displayName": "CTSV",    "isActive": true, "color": "#E74C3C" },
            { "value": "all",     "displayName": "Tat ca",  "isActive": true, "color": "#95A5A6" }
        ]
    }' 2>/dev/null || echo -e "\n000")
HTTP_CODE_META=$(echo "$RESPONSE" | tail -n1)
if [ "$HTTP_CODE_META" = "201" ]; then
    log_success "Create Metadata Type — department (HTTP 201)"
    echo "$RESPONSE" | sed '$d' | python3 -m json.tool 2>/dev/null
elif [ "$HTTP_CODE_META" = "409" ]; then
    log_info "Create Metadata Type — department ton tai (409), kich hoat lai..."
    PATCH_RESP=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/metadata/department" \
        -H "Content-Type: application/json" \
        -H "${AUTH_HEADER}" \
        -d '{"isActive": true}' 2>/dev/null || echo -e "\n000")
    PATCH_CODE=$(echo "$PATCH_RESP" | tail -n1)
    if [ "$PATCH_CODE" = "200" ]; then
        log_success "Create Metadata Type — department (da kich hoat lai, HTTP 200)"
    else
        log_error "Create Metadata Type — department — Khong the kich hoat lai (HTTP $PATCH_CODE)"
        echo "$PATCH_RESP" | sed '$d'
    fi
else
    log_error "Create Metadata Type — department — Expected 201/409, got $HTTP_CODE_META"
    echo "$RESPONSE" | sed '$d'
fi

# 5.2 Kiem tra system metadata type: access_scope
log_info "GET /api/metadata/access_scope — Xac nhan system type ton tai"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata/access_scope" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get System Metadata Type — access_scope (seeded)"

# 5.3 Liet ke
log_info "GET /api/metadata — Liet ke tat ca"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Metadata Types"

# 5.4 Chi tiet
log_info "GET /api/metadata/${METADATA_KEY} — Chi tiet"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "${AUTH_HEADER}" "${API_URL}/metadata/${METADATA_KEY}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Get Metadata Type — department"

# 5.5 Cap nhat — them gia tri htqt
log_info "PATCH /api/metadata/${METADATA_KEY} — Them gia tri htqt (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X PATCH "${API_URL}/metadata/${METADATA_KEY}" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d '{
        "allowedValues": [
            { "value": "dao_tao", "displayName": "Dao tao", "isActive": true, "color": "#3498DB" },
            { "value": "khcn",    "displayName": "KHCN",    "isActive": true, "color": "#2ECC71" },
            { "value": "ctsv",    "displayName": "CTSV",    "isActive": true, "color": "#E74C3C" },
            { "value": "htqt",    "displayName": "HTQT",    "isActive": true, "color": "#9B59B6" },
            { "value": "all",     "displayName": "Tat ca",  "isActive": true, "color": "#95A5A6" }
        ]
    }' 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Update Metadata Type — them htqt"

# 5.6 Xoa mot gia tri (hard delete value)
log_info "DELETE /api/metadata/${METADATA_KEY}/values/htqt — Xoa gia tri htqt"
# Bo qua loi neu dang dung, se test delete 1 gia tri moi tao
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/metadata/${METADATA_KEY}/values/htqt" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
HTTP_VAL=$(echo "$RESPONSE" | tail -n1)
if [ "$HTTP_VAL" = "200" ] || [ "$HTTP_VAL" = "409" ]; then
    log_success "Delete Metadata Value test (HTTP $HTTP_VAL - handled)"
else
    log_error "Delete Metadata Value test failed (HTTP $HTTP_VAL)"
fi

# 5.7 Thu xoa system type (expect 403)
log_info "DELETE /api/metadata/access_scope — Xoa system type (expect 403)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/metadata/access_scope" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "403" "Cannot delete system metadata"

# 5.8 Xoa metadata type (Hard Delete)
log_info "DELETE /api/metadata/test_to_delete — Test Hard Delete metadata type"
# Tao tam mot type de xoa
curl -s -X POST "${API_URL}/metadata" -H "Content-Type: application/json" -H "${AUTH_HEADER}" \
    -d '{"key": "test_to_delete", "displayName": "Delete Me", "description": "test"}' > /dev/null
RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/metadata/test_to_delete" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "204" "Hard Delete Metadata Type"

# 5.7 Thu tao metadata khong co token (expect 401)
log_info "POST /api/metadata — khong co token (expect 401)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/metadata" \
    -H "Content-Type: application/json" \
    -d '{"key": "test_unauth", "displayName": "Unauth"}' \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "401" "Create Metadata — no token -> 401"

# ==============================================================================
# 6. FILE MANAGEMENT
# ==============================================================================
log_header "5. FILE MANAGEMENT"

create_test_files
TEST_FILE="scripts/uploads/test_document.txt"
TEST_FILE_2="scripts/uploads/test_document_2.txt"

# 6.1 Upload file vao store da tao
if [ -n "$STORE_ID" ]; then
    log_info "POST /api/files — Upload vao store $STORE_ID (require_admin)"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
        -H "${AUTH_HEADER}" \
        -F "file=@${TEST_FILE}" \
        -F "display_name=Quy che dao tao ${TIMESTAMP}" \
        -F "store_id=${STORE_ID}" \
        -F 'custom_metadata={"department":"dao_tao","access_scope":"cong_khai","academic_year":"2025-2026"}' \
        2>/dev/null || echo -e "\n000")
    if check_response "$RESPONSE" "201" "Upload File (store_id)"; then
        BODY=$(echo "$RESPONSE" | sed '$d')
        FILE_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('file_id',''))" 2>/dev/null || echo "")
        log_info "  -> file_id = $FILE_ID"
    fi
else
    log_info "POST /api/files — Upload (default store) (require_admin)"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
        -H "${AUTH_HEADER}" \
        -F "file=@${TEST_FILE}" \
        -F "display_name=Quy che dao tao ${TIMESTAMP}" \
        -F 'custom_metadata={"department":"dao_tao","access_scope":"cong_khai","academic_year":"2025-2026"}' \
        2>/dev/null || echo -e "\n000")
    if check_response "$RESPONSE" "201" "Upload File (default store)"; then
        BODY=$(echo "$RESPONSE" | sed '$d')
        FILE_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('file_id',''))" 2>/dev/null || echo "")
        log_info "  -> file_id = $FILE_ID"
    fi
fi

# 6.2 Upload file thu hai
log_info "POST /api/files — Upload file thu hai (require_admin)"
UPLOAD_ARGS=(-F "file=@${TEST_FILE_2}" -F "display_name=Quy dinh hoc bong ${TIMESTAMP}")
[ -n "$STORE_ID" ] && UPLOAD_ARGS+=(-F "store_id=${STORE_ID}")
UPLOAD_ARGS+=(-F 'custom_metadata={"department":"dao_tao","access_scope":"cong_khai","academic_year":"2025-2026"}')
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -H "${AUTH_HEADER}" \
    "${UPLOAD_ARGS[@]}" 2>/dev/null || echo -e "\n000")
if check_response "$RESPONSE" "201" "Upload File thu hai"; then
    BODY=$(echo "$RESPONSE" | sed '$d')
    FILE_ID_2=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('file_id',''))" 2>/dev/null || echo "")
    log_info "  -> file_id_2 = $FILE_ID_2"
fi

# 6.3 Liet ke files
log_info "GET /api/files — Liet ke tat ca (require_auth)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?page=1&limit=20" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files"

# 6.4 Loc theo store
if [ -n "$STORE_ID" ]; then
    log_info "GET /api/files?store_id=${STORE_ID} — Loc theo store (require_auth)"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?store_id=${STORE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "List Files by store_id"
fi

# 6.5 Loc theo status
log_info "GET /api/files?status=active — Loc theo status=active (require_auth)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files?status=active" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "List Files by status=active"

# 6.6 Discovery tu Gemini
log_info "GET /api/files/check-sync — Comparison across DB, R2, Gemini (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/check-sync" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Check Sync Status"

# 6.7 Chi tiet file
if [ -n "$FILE_ID" ]; then
    log_info "GET /api/files/${FILE_ID} — Chi tiet file (require_auth)"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Get File by ID"
else
    log_skip "Get File by ID — bo qua (FILE_ID chua duoc set)"
fi

# 6.8 Download file
if [ -n "$FILE_ID" ]; then
    log_info "GET /api/files/${FILE_ID}/download — Download file (require_auth)"
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/files/${FILE_ID}/download" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        log_success "Download File (HTTP 200)"
    else
        log_error "Download File — Expected 200, got $HTTP_CODE"
    fi
else
    log_skip "Download File — bo qua (FILE_ID chua duoc set)"
fi

# 6.9 Batch upload
log_info "POST /api/files/batch — Batch upload 2 files (require_admin)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files/batch" \
    -H "${AUTH_HEADER}" \
    -F "files=@${TEST_FILE}" \
    -F "files=@${TEST_FILE_2}" \
    -F "display_names=[\"Batch 1 ${TIMESTAMP}\", \"Batch 2 ${TIMESTAMP}\"]" \
    -F 'metadata_list=[{"department":"dao_tao","access_scope":"cong_khai","academic_year":"2025-2026"},{"department":"khcn","access_scope":"cong_khai","academic_year":"2025-2026"}]' \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "201" "Batch Upload Files"

# 6.10 Sync files (thuc hien sync thuc te)
log_info "POST /api/files/sync — Trigger file sync across R2/Gemini"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files/sync" \
    -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Sync Files"

# 6.11 Detail check
if [ -n "$FILE_ID" ]; then
    log_info "GET /api/files/${FILE_ID} — Detail check (require_auth)"
    RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/${FILE_ID}" \
        -H "${AUTH_HEADER}" \
        2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Get File Detail"

else
    log_skip "File detail — bo qua (FILE_ID chua duoc set)"
fi

# 6.13 Xoa tat ca files trong store
if [ -n "$STORE_ID" ]; then
    log_info "DELETE /api/files/all?store_id=${STORE_ID} — Xoa tat ca file trong store"
    RESPONSE=$(curl -s -w "\n%{http_code}" -X DELETE "${API_URL}/files/all?store_id=${STORE_ID}" \
        -H "${AUTH_HEADER}" 2>/dev/null || echo -e "\n000")
    check_response "$RESPONSE" "200" "Delete All Files in Store"
fi

# 6.11 Error case: File khong ton tai
log_info "GET /api/files/000000000000000000000000 — File khong ton tai (expect 404)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${API_URL}/files/000000000000000000000000" \
    -H "${AUTH_HEADER}" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "404" "Get File — not found -> 404"

# 6.12 Error case: Upload khong co token (expect 401)
log_info "POST /api/files — khong co token (expect 401)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/files" \
    -F "file=@${TEST_FILE}" \
    -F "display_name=Unauthorized Upload" \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "401" "Upload File — no token -> 401"

# ==============================================================================
# 7. CHAT
# ==============================================================================
log_header "6. CHAT"

# 7.1 Chat query - student role
log_info "POST /api/chat/query — Student query (require_auth)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"question\": \"Dieu kien tot nghiep cua truong la gi?\",
        \"user_context\": {
            \"user_id\": \"sv001_test\",
            \"name\": \"Nguyen Test\",
            \"cohort\": \"K20\",
            \"role\": \"student\"
        },
        \"chat_history\": [],
        \"store_id\": \"${STORE_ID}\"
    }" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — student role"

# 7.2 Chat query - voi metadata filter
log_info "POST /api/chat/query — With metadata_filter (require_auth)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"question\": \"So tin chi toi thieu moi ky la bao nhieu?\",
        \"user_context\": {
            \"user_id\": \"sv002_test\",
            \"name\": \"Tran Test\",
            \"cohort\": \"K21\",
            \"role\": \"student\"
        },
        \"chat_history\": [],
        \"store_id\": \"${STORE_ID}\",
        \"metadata_filter\": {
            \"department\": \"dao_tao\",
            \"access_scope\": \"cong_khai\"
        }
    }" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — with metadata_filter"

# 7.3 Chat query - staff role
log_info "POST /api/chat/query — Staff role (require_auth)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"question\": \"Tong hop cac quy che dang co trong he thong?\",
        \"user_context\": {
            \"user_id\": \"staff001_test\",
            \"name\": \"Staff Test\",
            \"cohort\": \"\",
            \"role\": \"staff\"
        },
        \"chat_history\": [],
        \"store_id\": \"${STORE_ID}\"
    }" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — staff role"

# 7.4 Chat query - co lich su hoi thoai
log_info "POST /api/chat/query — With chat history (require_auth)"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"question\": \"Vay diem GPA toi thieu la bao nhieu de tot nghiep?\",
        \"user_context\": {
            \"user_id\": \"sv001_test\",
            \"name\": \"Nguyen Test\",
            \"cohort\": \"K20\",
            \"role\": \"student\"
        },
        \"chat_history\": [
            {
                \"role\": \"user\",
                \"content\": \"Dieu kien tot nghiep la gi?\",
                \"timestamp\": \"2026-03-11T10:00:00\"
            },
            {
                \"role\": \"assistant\",
                \"content\": \"De tot nghiep sinh vien can hoan thanh toan bo hoc phan va dat GPA toi thieu...\",
                \"timestamp\": \"2026-03-11T10:00:05\"
            }
        ],
        \"store_id\": \"${STORE_ID}\"
    }" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query — with history"

# 7.5 Chat stream (SSE)
log_info "POST /api/chat/stream — Streaming SSE (require_auth) — doc 5 giay"
STREAM_OUTPUT=$(curl -s -N --max-time 5 -X POST "${API_URL}/chat/stream" \
    -H "Content-Type: application/json" \
    -H "Accept: text/event-stream" \
    -H "${AUTH_HEADER}" \
    -d "{
        \"question\": \"Can bao nhieu tin chi de tot nghiep?\",
        \"user_context\": {
            \"user_id\": \"sv001_test\",
            \"name\": \"Nguyen Test\",
            \"cohort\": \"K20\",
            \"role\": \"student\"
        },
        \"chat_history\": [],
        \"store_id\": \"${STORE_ID}\"
    }" 2>/dev/null)

if echo "$STREAM_OUTPUT" | grep -q '"chunk"'; then
    log_success "Chat Stream — nhan duoc SSE chunks"
    echo "$STREAM_OUTPUT" | head -5
elif echo "$STREAM_OUTPUT" | grep -q '"done":true'; then
    log_success "Chat Stream — nhan duoc done event"
else
    if [ -z "$STREAM_OUTPUT" ]; then
        log_warning "Chat Stream — khong co du lieu trong 5 giay (store co the chua co file active)"
    else
        log_error "Chat Stream — Response khong dung format SSE"
        echo "$STREAM_OUTPUT" | head -3
    fi
fi

# 7.6 Chat query khong co token - endpoint nay public
log_info "POST /api/chat/query - no token, public endpoint"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/chat/query" \
    -H "Content-Type: application/json" \
    -d '{"question":"test","user_context":{"user_id":"x","name":"x","cohort":"K20","role":"student"},"chat_history":[]}' \
    2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Chat Query - no token"

# ==============================================================================
# 8. CLEANUP (tuy chon)
# ==============================================================================
log_header "7. CLEANUP (tuy chon)"

log_warning "Bo qua cleanup tu dong de giu du lieu test."
log_warning "De cleanup thu cong (TOKEN da duoc set trong bien TOKEN):"
if [ -n "$FILE_ID" ]; then
    log_info "  Xoa file 1:  curl -X DELETE -H \"${AUTH_HEADER}\" ${API_URL}/files/${FILE_ID}"
fi
if [ -n "$FILE_ID_2" ]; then
    log_info "  Xoa file 2:  curl -X DELETE -H \"${AUTH_HEADER}\" ${API_URL}/files/${FILE_ID_2}"
fi
if [ -n "$STORE_ID" ]; then
    log_info "  Xoa store:   curl -X DELETE -H \"${AUTH_HEADER}\" '${API_URL}/stores/${STORE_ID}?force=true'"
fi
log_info "  Xoa metadata: curl -X DELETE -H \"${AUTH_HEADER}\" ${API_URL}/metadata/${METADATA_KEY}"

# ==============================================================================
# SUMMARY
# ==============================================================================
log_header "KET QUA"

TOTAL=$((TESTS_PASSED + TESTS_FAILED + TESTS_SKIPPED))
echo ""
echo -e "  Tong:     ${TOTAL}"
echo -e "  ${GREEN}Passed:   ${TESTS_PASSED}${NC}"
echo -e "  ${RED}Failed:   ${TESTS_FAILED}${NC}"
echo -e "  ${CYAN}Skipped:  ${TESTS_SKIPPED}${NC}"
echo ""

if [ "$TESTS_FAILED" -eq 0 ]; then
    echo -e "${GREEN}Tat ca test deu PASS${NC}"
else
    echo -e "${RED}Co ${TESTS_FAILED} test FAILED${NC}"
    echo ""
    echo "Luu y:"
    echo "  - Chat/File co the FAIL neu store chua co file status=active"
    echo "  - Auth verify (gRPC) co the FAIL neu NestJS chua chay"
    echo "  - Store/File/Metadata operations co the FAIL neu token het han"
    exit 1
fi

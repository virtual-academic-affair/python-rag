#!/bin/bash

# ====================================
# Shared Configuration & Helpers
# ====================================

# Configuration
BASE_URL="${AI_SERVICE_URL:-http://localhost:8000}"
API_URL="${BASE_URL}/api"

# Output file (if not inherited)
OUTPUT_DIR="scripts/test_results"
mkdir -p "$OUTPUT_DIR"

# JWT Tokens
ADMIN_TOKEN=""
# Student token 
STUDENT_TOKEN=""

AUTH_HEADER="Authorization: Bearer ${ADMIN_TOKEN}"
STUDENT_AUTH_HEADER="Authorization: Bearer ${STUDENT_TOKEN}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Counters (exported for master script)
if [ -z "$TESTS_PASSED" ]; then export TESTS_PASSED=0; fi
if [ -z "$TESTS_FAILED" ]; then export TESTS_FAILED=0; fi
if [ -z "$TESTS_SKIPPED" ]; then export TESTS_SKIPPED=0; fi

# Helper functions
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[PASS]${NC} $1"; export TESTS_PASSED=$((TESTS_PASSED + 1)); }
log_error()   { echo -e "${RED}[FAIL]${NC} $1"; export TESTS_FAILED=$((TESTS_FAILED + 1)); }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_skip()    { echo -e "${CYAN}[SKIP]${NC} $1"; export TESTS_SKIPPED=$((TESTS_SKIPPED + 1)); }

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
        echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body" | head -n 20
        return 0
    else
        log_error "$test_name — Expected $expected_code, got $http_code"
        echo "$body" | head -n 50
        return 1
    fi
}

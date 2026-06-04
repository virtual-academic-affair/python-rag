#!/bin/bash

# ====================================
# Shared Configuration & Helpers
# ====================================

# Default Configuration
API_URL=${AI_SERVICE_URL:-"http://localhost:8000/api"}
BASE_URL=${AI_BASE_URL:-"http://localhost:8000"}

# Load JWT config dynamically from .env to avoid hardcoding credentials
DIR_OF_COMMON="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$DIR_OF_COMMON/../../.env"

if [ -f "$ENV_FILE" ]; then
    if [ -z "$JWT_SECRET" ]; then
        JWT_SECRET=$(grep -E "^JWT_SECRET=" "$ENV_FILE" | cut -d'=' -f2-)
    fi
    if [ -z "$JWT_AUDIENCE" ]; then
        JWT_AUDIENCE=$(grep -E "^JWT_TOKEN_AUDIENCE=" "$ENV_FILE" | cut -d'=' -f2-)
    fi
    if [ -z "$JWT_ISSUER" ]; then
        JWT_ISSUER=$(grep -E "^JWT_TOKEN_ISSUER=" "$ENV_FILE" | cut -d'=' -f2-)
    fi
fi

# Clean quotes from variables
JWT_SECRET=$(echo "$JWT_SECRET" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
JWT_AUDIENCE=$(echo "$JWT_AUDIENCE" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
JWT_ISSUER=$(echo "$JWT_ISSUER" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")

ADMIN_TOKEN=$(python3 -c "
import jwt, time
payload = {
    'sub': 'admin-sub',
    'email': 'admin@hcmus.edu.vn',
    'role': 'admin',
    'studentCode': None,
    'enrollmentYear': None,
    'aud': '$JWT_AUDIENCE',
    'iss': '$JWT_ISSUER',
    'exp': int(time.time()) + 3600
}
print(jwt.encode(payload, '$JWT_SECRET', algorithm='HS256'))
" 2>/dev/null)

STUDENT_TOKEN=$(python3 -c "
import jwt, time
payload = {
    'sub': '57',
    'email': 'student@student.hcmus.edu.vn',
    'role': 'student',
    'studentCode': 'SV220001',
    'enrollmentYear': 2022,
    'aud': '$JWT_AUDIENCE',
    'iss': '$JWT_ISSUER',
    'exp': int(time.time()) + 3600
}
print(jwt.encode(payload, '$JWT_SECRET', algorithm='HS256'))
" 2>/dev/null)

AUTH_HEADER="Authorization: Bearer ${ADMIN_TOKEN}"
STUDENT_AUTH_HEADER="Authorization: Bearer ${STUDENT_TOKEN}"

# Output file (if not inherited)
OUTPUT_DIR="scripts/test_results"
mkdir -p "$OUTPUT_DIR"

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

run_test() {
    local script_name="$1"
    local script_path="$(dirname "$0")/$script_name"
    if [ -f "$script_path" ]; then
        log_info "Running $script_name..."
        source "$script_path"
    else
        log_warning "Test script NOT found: $script_name"
        export TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
    fi
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

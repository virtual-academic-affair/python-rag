#!/bin/bash
source "$(dirname "$0")/common.sh"

log_header "1. HEALTH CHECK"

log_info "GET /health"
RESPONSE=$(curl -s -w "\n%{http_code}" "${BASE_URL}/health" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Health check"

log_info "GET / — Root API"
RESPONSE=$(curl -s -w "\n%{http_code}" "${BASE_URL}/" 2>/dev/null || echo -e "\n000")
check_response "$RESPONSE" "200" "Root API endpoint"

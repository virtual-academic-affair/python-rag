#!/bin/bash

# ====================================
# Master Test Execution Script
# ====================================

# Initialize shared state
mkdir -p scripts/test_results
rm -f scripts/test_results/*.txt

# Source common for initialization
source "$(dirname "$0")/common.sh"

# Output file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="scripts/test_results/full_test_${TIMESTAMP}.txt"

# Tee stdout + stderr
exec > >(tee -a "$OUTPUT_FILE") 2>&1

echo "Master Test Started at: $(date)"
echo "Output: $OUTPUT_FILE"

# Run modules
run_test "test_health.sh"
run_test "test_classification.sh"
run_test "test_metadata.sh"
run_test "test_files.sh"
run_test "test_debug.sh"

log_header "RATE LIMIT PAUSE"
echo "Sleeping for 65 seconds to avoid Gemini API rate limit before testing chat..."
sleep 65

run_test "test_chat.sh"
run_test "test_cache_ttl.sh"

# Final Summary
log_header "FINAL SUMMARY"
echo -e "  Passed:   ${GREEN}${TESTS_PASSED}${NC}"
echo -e "  Failed:   ${RED}${TESTS_FAILED}${NC}"
echo -e "  Skipped:  ${CYAN}${TESTS_SKIPPED}${NC}"
echo ""

if [ "$TESTS_FAILED" -eq 0 ]; then
    echo -e "${GREEN}SUCCESS: All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}FAILURE: ${TESTS_FAILED} tests failed.${NC}"
    exit 1
fi

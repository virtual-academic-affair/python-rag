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
source "$(dirname "$0")/test_health.sh" || return 1
source "$(dirname "$0")/test_classification.sh"
source "$(dirname "$0")/test_stores.sh"
source "$(dirname "$0")/test_metadata.sh"
source "$(dirname "$0")/test_files.sh"
source "$(dirname "$0")/test_chat.sh"

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

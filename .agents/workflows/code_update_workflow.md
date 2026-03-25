---
description: Workflow for reviewing code and updating documentation after edits
---

After any code modification:

1. **Review Code**: 
   - Check for syntax errors, logical consistency, and adherence to project patterns.
   - Ensure variables and functions are named according to existing conventions (e.g., camelCase for API/JSON, snake_case for internal Python).
   - Use `run_command` to run the specific test script related to your changes (e.g., `bash scripts/test/test_classification.sh`). Avoid using `run_all.sh` unless changes are broad.

2. **Verify Correctness**:
   - If issues are found, fix them and repeat Step 1.

3. **Update Documentation**:
   - Once verified, update the following files to reflect any changes in API or logic:
     - [api.txt](file:///Users/trangvu/Documents/Phuc/giao_vu/email/test/python-rag/docs/api.txt)
     - [AI_Service.postman_collection.json](file:///Users/trangvu/Documents/Phuc/giao_vu/email/test/python-rag/docs/AI_Service.postman_collection.json)
     - [project-overview.txt](file:///Users/trangvu/Documents/Phuc/giao_vu/email/test/python-rag/docs/project-overview.txt)
     - [README.md](file:///Users/trangvu/Documents/Phuc/giao_vu/email/test/python-rag/README.md)

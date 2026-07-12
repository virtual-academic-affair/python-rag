"""
Step Formatter — Chuyển đổi raw pipeline activity sang schema public {type, content}.

Tất cả public step đều được trả về dưới dạng:
    {"type": "<loại>", "content": "<mô tả ngôn ngữ tự nhiên tiếng Việt>"}

Hàm này là pure function (không có side effect, không I/O) và có thể được
tái sử dụng bởi bất kỳ module nào cần định dạng step để stream hoặc lưu DB.
"""

from __future__ import annotations


def simplify_step(step: dict, candidate_files: list[dict] | None = None) -> dict:
    """
    Chuyển đổi một pipeline step có cấu trúc phức tạp sang schema thống nhất:
        {"type": str, "content": str}

    Args:
        step: Dict chứa thông tin của step (phải có trường "type").
        candidate_files: Danh sách tài liệu ứng viên, cần thiết để giải mã
                         file_id thành file_name thân thiện trong step "call".

    Returns:
        Dict với đúng 2 trường: "type" và "content" (tiếng Việt tự nhiên).
        Nếu step_type không xác định, trả về step gốc.
    """
    step_type = step.get("type")
    if not step_type:
        return step

    if step_type == "query_analysis":
        original = step.get("original_question", "")
        effective = step.get("effective_question", "")
        needs_rag = step.get("needs_rag", True)
        metadata_filter = step.get("metadata_filter")

        if needs_rag:
            filter_desc = []
            if metadata_filter:
                if metadata_filter.get("enrollment_year"):
                    ey = metadata_filter["enrollment_year"]
                    if ey.get("from_year") == ey.get("to_year"):
                        filter_desc.append(f"Khóa sinh viên: {ey.get('from_year')}")
                    else:
                        filter_desc.append(f"Khóa sinh viên: {ey.get('from_year')}-{ey.get('to_year')}")
                if metadata_filter.get("academic_year"):
                    ay = metadata_filter["academic_year"]
                    if ay.get("from_year") == ay.get("to_year"):
                        filter_desc.append(f"Năm học: {ay.get('from_year')}")
                    else:
                        filter_desc.append(f"Năm học: {ay.get('from_year')}-{ay.get('to_year')}")
                if metadata_filter.get("type"):
                    t = metadata_filter["type"]
                    type_map = {
                        "ctdt": "Chương trình đào tạo",
                        "cong_van": "Công văn/Thông báo",
                        "quyet_dinh": "Quyết định/Quy chế"
                    }
                    if isinstance(t, list):
                        friendly_types = [type_map.get(x, x) for x in t if x]
                        if friendly_types:
                            filter_desc.append(f"Loại tài liệu: {', '.join(friendly_types)}")
                    elif isinstance(t, str):
                        filter_desc.append(f"Loại tài liệu: {type_map.get(t, t)}")
            filter_str = f" (Bộ lọc: {', '.join(filter_desc)})" if filter_desc else ""
            content = f"Phân tích câu hỏi: câu hỏi gốc là '{original}', được chuẩn hóa thành '{effective}'{filter_str}."
        else:
            content = f"Phân tích câu hỏi: '{original}' (Không cần tra cứu tài liệu)."

    elif step_type == "corpus_traversal":
        action = step.get("action")
        if action == "list_roots":
            content = f"Đã tìm thấy {step.get('topic_count', 0)} nhóm chủ đề có dữ liệu phù hợp."
        elif action == "expand":
            content = f"Đã mở chủ đề {step.get('node_title', 'đã chọn')} và tìm thấy {step.get('child_count', 0)} chủ đề con."
        elif action == "inspect":
            scope = "chủ đề này" if step.get("scope") == "direct" else "toàn bộ nhánh chủ đề"
            content = (
                f"Đã kiểm tra {step.get('sample_file_count', 0)} tài liệu và "
                f"{step.get('sample_faq_count', 0)} FAQ mẫu trong {scope} {step.get('node_title', 'đã chọn')}."
            )
        elif action == "select":
            topics = step.get("topics") or []
            titles = [item.get("nodeTitle") or item.get("nodeKey") for item in topics if isinstance(item, dict)]
            topic_text = ", ".join(filter(None, titles)) or "các chủ đề liên quan"
            content = (
                f"Đã chọn {topic_text}: {step.get('file_count', 0)} tài liệu và "
                f"{step.get('faq_count', 0)} FAQ ứng viên."
            )
        else:
            content = "Không tìm thấy chủ đề phù hợp trong Corpus."

    elif step_type == "faq_retrieval":
        count = step.get("faq_count", 0)
        if count:
            content = f"Đã chọn {count} FAQ liên quan để kiểm tra câu trả lời."
        else:
            content = "Không tìm thấy FAQ phù hợp."

    elif step_type == "faq_answer":
        questions = step.get("questions") or []
        if step.get("answered"):
            if len(questions) == 1:
                content = f"FAQ đã trả lời đầy đủ câu hỏi: '{questions[0]}'."
            elif questions:
                content = f"{len(questions)} FAQ đã cùng trả lời đầy đủ câu hỏi."
            else:
                content = "FAQ đã trả lời đầy đủ câu hỏi."
        else:
            content = "FAQ chưa đủ để trả lời toàn bộ câu hỏi, tiếp tục tra cứu tài liệu."

    elif step_type == "file_retrieval":
        files = step.get("candidate_files") or []
        file_names = [f.get("file_name") for f in files if f.get("file_name")]
        if file_names:
            content = f"Tìm thấy {len(file_names)} tài liệu liên quan: {', '.join(file_names)}."
        else:
            content = "Không tìm thấy tài liệu liên quan nào trong cơ sở dữ liệu."

    elif step_type == "call":
        name = step.get("name")
        args = step.get("args") or {}

        # Giải mã file_id → tên tài liệu thân thiện
        raw_fid = str(args.get("file_id", ""))
        fid = raw_fid.strip().strip("[]")
        file_name = "tài liệu quy chế"
        if candidate_files:
            for c in candidate_files:
                c_fid = str(c.get("file_id", "")).strip()
                if c_fid == fid:
                    file_name = c.get("file_name", "tài liệu")
                    break
            else:
                # Thử khớp theo index số (Agent có thể dùng "1", "2",... thay vì UUID)
                if fid.isdigit():
                    idx = int(fid) - 1
                    if 0 <= idx < len(candidate_files):
                        file_name = candidate_files[idx].get("file_name", "tài liệu")

        if name == "get_document_structure":
            content = f"Đang tra cứu cấu trúc mục lục của '{file_name}'."
        elif name == "get_page_content":
            pages = args.get("pages", "")
            content = f"Đang đọc nội dung chi tiết (dòng {pages}) từ '{file_name}'."
        else:
            content = f"Đang thực hiện tra cứu qua công cụ {name}."

    else:
        # Giữ nguyên content nếu đây là loại step không cần chuyển đổi (reasoning, text, v.v.)
        content = step.get("content", "")

    public_type = "document_read" if step_type == "call" else step_type
    return {"type": public_type, "content": content}

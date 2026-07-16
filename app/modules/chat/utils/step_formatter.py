"""
Step Formatter — chuyển raw pipeline activity sang public step tối giản.

Hàm này là pure function (không có side effect, không I/O) và có thể được
tái sử dụng bởi bất kỳ module nào cần định dạng step để stream hoặc lưu DB.
"""

from __future__ import annotations


def simplify_step(step: dict, candidate_files: list[dict] | None = None) -> dict:
    """
    Corpus traversal giữ action và node key; các step khác giữ type/content.

    Args:
        step: Dict chứa thông tin của step (phải có trường "type").
        candidate_files: Danh sách tài liệu ứng viên, cần thiết để giải mã
                         file_id thành file_name thân thiện trong step "call".

    Returns:
        Public step đã được rút gọn.
    """
    step_type = step.get("type")
    if not step_type:
        return step

    if step_type == "query_analysis":
        effective_question = str(step.get("effective_question") or "").strip()
        content = effective_question or "Phân tích câu hỏi."

    elif step_type == "corpus_tree":
        return {
            "type": "corpus_tree",
            "content": step.get("content", ""),
            "tree": step.get("tree") or [],
        }

    elif step_type == "corpus_traversal":
        action = step.get("action")
        result = {
            "type": "corpus_traversal",
            "action": action,
            "content": step.get("content", ""),
        }
        if step.get("node_key"):
            result["nodeKey"] = step["node_key"]
        if step.get("node_keys"):
            result["nodeKeys"] = step["node_keys"]
        return result

    elif step_type == "reasoning":
        return {"type": "reasoning", "content": step.get("content", "")}

    elif step_type == "faq_retrieval":
        count = step.get("faq_count", 0)
        if count:
            content = f"Chọn {count} FAQ liên quan để kiểm tra câu trả lời."
        else:
            content = "Không tìm thấy FAQ phù hợp."

    elif step_type == "faq_answer":
        questions = step.get("questions") or []
        if step.get("answered"):
            if len(questions) > 1:
                content = f"{len(questions)} FAQ cùng trả lời đầy đủ câu hỏi."
            else:
                content = "FAQ trả lời đầy đủ câu hỏi."
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

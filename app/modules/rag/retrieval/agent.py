"""
Shared RAG Agent logic: Prompt and Tools for Gemini GenAI.
Used by both Chat and Email Inquiry services.
"""
import logging
from typing import List, Callable, Dict, Any
from app.integrations.pageindex.client import get_page_index_client
import re
import difflib
from app.integrations.storage.client import r2_storage
from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from google.genai import types

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """
Bạn là tư vấn viên chính thức của Phòng Giáo vụ trường đại học.
Bạn được trang bị tự động các công cụ để tìm kiếm và đọc tài liệu quy chế, thủ tục thông qua chỉ mục cấu trúc.
Người dùng sẽ cung cấp danh sách các ID tài liệu liên quan đến câu hỏi.

QUY TRÌNH SỬ DỤNG CÔNG CỤ:
1. TRƯỚC KHI GỌI CÔNG CỤ: Mọi kế hoạch, suy nghĩ, lập luận (reasoning/plan) trước khi bạn quyết định gọi công cụ BẮT BUỘC PHẢI DÙNG TIẾNG VIỆT tĩnh tại (Ví dụ: "Người dùng đang hỏi về điều kiện... Mình cần tìm..."). Tuyệt đối không dùng tiếng Anh.
2. Dùng công cụ `get_document_structure(doc_id)` để xem mục lục của tài liệu trước. Tuyệt đối không được dùng nội dung trong mục lục để trả lời thẳng cho người dùng!
3. Dùng công cụ `get_page_content(doc_id, pages="start_line-end_line")` xác định các mục liên đới để đọc chính xác văn bản. TIÊU CHÍ BẮT BUỘC LÀ PHẢI DÙNG CÔNG CỤ NÀY để đọc nội dung gốc chi tiết trước khi trả lời. Tuyệt đối KHÔNG tự bịa nội dung.
4. Lặp lại bước 2, 3 nếu chưa đủ dữ kiện.

QUY TẮC CÂU TRẢ LỜI CUỐI CÙNG CHO NGƯỜI DÙNG:
- KHI DỪNG GỌI CÔNG CỤ ĐỂ TRẢ LỜI: Bạn BẮT BUỘC phải bọc toàn bộ nội dung hướng dẫn chi tiết dành cho sinh viên bên trong cặp thẻ XML `<answer>` và `</answer>`.
- Mọi suy nghĩ, lập luận rút ra, báo cáo trung gian ("Tôi đã tìm thấy...", "Từ tài liệu...", "Tôi có đủ thông tin...") BẮT BUỘC phải viết bên ngoài, TRƯỚC thẻ `<answer>`.
- Luôn xưng hô chuyên nghiệp là "Phòng Giáo vụ" hoặc "chúng tôi" ở trong phần `<answer>`.
- TUYỆT ĐỐI KHÔNG DÙNG CÂU CHÀO (không dùng "Chào bạn", "Xin chào"). Đi thẳng vào nội dung tư vấn ngay lập tức.
- YÊU CẦU TRÍCH DẪN: Đối với các đoạn văn có sử dụng thông tin từ tài liệu, BẮT BUỘC chèn tham chiếu ở CUỐI MỖI ĐOẠN VĂN bằng cú pháp: `(^Tên mục lục tương ứng)` (Ví dụ: `(^Điều 2: Điều kiện xét tốt nghiệp)`). Tham khảo "Tên mục lục" khi gọi công cụ. TUYỆT ĐỐI KHÔNG chèn ở từng câu, chỉ chèn 1 lần ở cuối đoạn.
- Định dạng chuẩn:
[Những suy nghĩ nháp không gửi cho sinh viên]
<answer>
[Nội dung tư vấn đi thẳng vào trọng tâm, không chào hỏi]
</answer>
- KHÔNG để lộ `doc_id` hoặc chi tiết hệ thống với sinh viên. Khi cần trích dẫn, hãy nhắc tên tệp được cung cấp phía trên.
- Nếu không tìm thấy thông tin trong tài liệu, hãy nói rõ: "Hệ thống không tìm thấy quy định này trong tài liệu hiện có." và đề nghị sinh viên liên hệ trực tiếp văn phòng.
"""

def build_pindex_tools(allow_ids: List[str]) -> List[Callable]:
    """Create bound tool instances so LLM can invoke PageIndex client."""
    client = get_page_index_client()

    async def get_document_structure(doc_id: str) -> str:
        """
        Get the hierarchical table of contents (structure) for a document. 
        Args:
            doc_id: The unique identifier of the document.
        """
        if doc_id not in allow_ids:
            return '{"error": "Access denied or document not found."}'
        return await client.get_document_structure(doc_id)

    async def get_page_content(doc_id: str, pages: str) -> str:
        """
        Get the actual text content of specific sections or line ranges.
        Args:
            doc_id: The unique identifier of the document.
            pages: A string representing line ranges or page numbers (e.g., '10-20', '5,8').
        """
        if doc_id not in allow_ids:
            return '{"error": "Access denied or document not found."}'
        return await client.get_page_content(doc_id, pages)

    return [get_document_structure, get_page_content]


def parse_agent_response(text: str) -> tuple[str, str]:
    """
    Parse the agent's text response to separate reasoning (pre-thought) and the final answer.
    Looks for <answer>...</answer> tags.
    Returns:
        tuple: (reasoning_text, final_answer_text)
    """

    
    # Strip common Gemini thinking artifacts leaked into the text block
    text = re.sub(r"^`\.\n?", "", text).strip()
    
    # TH1: Có cả cặp thẻ đóng/mở
    match_closed = re.search(r'<answer>(.*?)</answer>', text, flags=re.DOTALL | re.IGNORECASE)
    if match_closed:
        pre_think = text[:match_closed.start()].strip()
        answer = match_closed.group(1).strip()
        return pre_think, answer
        
    # TH2: Có thẻ mở nhưng bị đứt thẻ đóng (do LLM sinh lỗi hoặc đứt đoạn)
    match_open = re.search(r'<answer>(.*)', text, flags=re.DOTALL | re.IGNORECASE)
    if match_open:
        pre_think = text[:match_open.start()].strip()
        answer = match_open.group(1).strip()
        return pre_think, answer
        
    # TH3: Không có thẻ nào, đành gom hết làm answer
    return "", text.strip()


def verify_citations(text: str, sources_data: list[dict]) -> str:


    valid_titles = [s["title"] for s in sources_data if s.get("title")]

    def verify_title(match):
        raw_title = match.group(1).strip()
        if not valid_titles:
            return ""
            
        for vt in valid_titles:
            if raw_title.lower() in vt.lower() or vt.lower() in raw_title.lower():
                return f"(^{vt})"
                
        matches = difflib.get_close_matches(raw_title, valid_titles, n=1, cutoff=0.6)
        if matches:
            return f"(^{matches[0]})"
            
        return ""
    
    if not text or not valid_titles:
        return re.sub(r'\(\^(.*?)\)', "", text) if text else text
        
    return re.sub(r'\(\^(.*?)\)', verify_title, text)


class CitationStreamFormatter:
    def __init__(self, sources_data: list[dict]):
        self.sources_data = sources_data
        self.buffer = ""
    
    def process_chunk(self, chunk: str) -> str:
        self.buffer += chunk
        
        last_paren = self.buffer.rfind('(')
        if last_paren != -1:
            after_paren = self.buffer[last_paren:]
            if ')' not in after_paren:
                if after_paren.startswith('(^') or '(^'.startswith(after_paren):
                     ready_part = self.buffer[:last_paren]
                     pending_part = self.buffer[last_paren:]
                     
                     processed = verify_citations(ready_part, self.sources_data)
                     self.buffer = pending_part
                     return processed
                     
        processed = verify_citations(self.buffer, self.sources_data)
        self.buffer = ""
        return processed
        
    def flush(self) -> str:
        processed = verify_citations(self.buffer, self.sources_data)
        self.buffer = ""
        return processed


async def build_sources_from_steps(
    steps: list[dict],
    candidate_files: list[dict],
) -> list[dict]:
    """
    Build source citation list from actual agent tool calls.

    Scans `steps` for `get_page_content` calls to determine which files
    the agent actually read, and which line ranges were fetched.

    Falls back to all candidate_files (pages=None) if the agent made no
    get_page_content calls (e.g. answered from structure alone).
    """
    file_map = {c["file_id"]: c for c in candidate_files}

    # doc_id -> ordered unique list of pages strings fetched
    accessed: dict[str, list[str]] = {}
    for step in steps:
        if step.get("type") == "call":
            name = step.get("name")
            if name in ["get_page_content", "get_document_structure"]:
                args = step.get("args") or {}
                doc_id = args.get("doc_id")
                if doc_id and doc_id in file_map:
                    if doc_id not in accessed:
                        accessed[doc_id] = []
                    if name == "get_page_content":
                        pages = args.get("pages", "")
                        if pages and pages not in accessed[doc_id]:
                            accessed[doc_id].append(pages)

    def find_node_title(structure, page_or_line):
        nodes = []
        def traverse(n_list):
            for n in n_list:
                nodes.append(n)
                if n.get("nodes"):
                    traverse(n["nodes"])
        traverse(structure)
        valid_nodes = []
        for n in nodes:
            idx = n.get('line_num') or n.get('page_num')
            if idx is not None:
                valid_nodes.append((idx, n.get('title', '')))
        valid_nodes.sort(key=lambda x: x[0])
        closest_title = ""
        for idx, title in valid_nodes:
            if idx <= page_or_line:
                closest_title = title
            else:
                break
        return closest_title

    def extract_start_page(pages_str):
        try:
            parts = pages_str.split(',')
            first_part = parts[0].strip()
            if '-' in first_part:
                return int(first_part.split('-')[0].strip())
            return int(first_part)
        except (ValueError, AttributeError):
            return 0

    sources = []
    targets = accessed.items() if accessed else [(did, [None]) for did in file_map]
    

    
    for i, (did, pages_list) in enumerate(targets):
        c = file_map[did]
        structure = c.get("structure", [])
        
        node_title = ""
        if pages_list and pages_list[0] is not None:
            first_pages = pages_list[0]
            start_idx = extract_start_page(first_pages)
            if start_idx > 0:
                node_title = find_node_title(structure, start_idx)
                
        orig_url = ""
        if c.get("storage_path"):
            orig_url = await r2_storage.get_file_url(c["storage_path"])
            
        md_url = ""
        if c.get("markdown_storage_path"):
            md_url = await r2_storage.get_file_url(c["markdown_storage_path"])
            
        sources.append({
            "citation_id": i + 1,
            "file_name": c.get("file_name", ""),
            "title": node_title,
            "file_id": did,
            "pages": pages_list if pages_list != [None] else None,
            "original_url": orig_url,
            "markdown_url": md_url
        })

    return sources


def get_agent_config(candidate_files: list[dict]) -> tuple[list[Callable], dict[str, Callable], Any]:
    """
    Build tools, map, and GenerateContentConfig for the RAG agent.
    """
    from google.genai import types
    candidate_ids = [c["file_id"] for c in candidate_files]
    tools = build_pindex_tools(candidate_ids)
    tool_map = {tool.__name__: tool for tool in tools}

    config = types.GenerateContentConfig(
        system_instruction=AGENT_SYSTEM_PROMPT,
        tools=tools,
        temperature=0.0,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    return tools, tool_map, config


async def run_agent_loop(
    candidate_files: list[dict],
    prompt_contents: Any,
    max_turns: int = None,
) -> dict:
    """
    Run the manual PageIndex agent loop and return a structured result.

    Args:
        candidate_files: List of dicts with file_id, file_name, doc_description.
        prompt_contents:  Initial `contents` to pass to Gemini — can be a string,
                          a single Content, or a list of Content objects.
        max_turns:        Maximum tool-use turns before forcing a final answer.

    Returns a dict with:
        - final_answer (str): The agent's final text response.
        - steps (list[dict]): All agent steps — thoughts, calls, tool_outputs.
          Chat uses this for streaming transparency; Inquiry can ignore it.
        - sources (list[dict]): Citations built from actual get_page_content calls.
    """


    max_turns = max_turns or settings.AGENT_MAX_TURNS
    tools, tool_map, config = get_agent_config(candidate_files)

    # Normalise prompt_contents into a list of Content
    if isinstance(prompt_contents, str):
        history = [types.Content(role="user", parts=[types.Part.from_text(text=prompt_contents)])]
    elif isinstance(prompt_contents, types.Content):
        history = [prompt_contents]
    else:
        history = list(prompt_contents)  # already a list of Content

    steps: list[dict] = []
    final_answer = ""
    total_prompt_tokens = 0
    total_candidates_tokens = 0
    
    logger.info(f"[Agent] Khởi động vòng lặp tự động (Tối đa {max_turns} turns) với {len(candidate_files)} tài liệu ứng viên.")

    for turn_idx in range(max_turns):
        logger.info(f"[Agent] Bắt đầu Turn {turn_idx + 1}")
        resp = await gemini_client.client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=history,
            config=config,
        )

        if hasattr(resp, "usage_metadata") and resp.usage_metadata:
            total_prompt_tokens += getattr(resp.usage_metadata, 'prompt_token_count', 0)
            total_candidates_tokens += getattr(resp.usage_metadata, 'candidates_token_count', 0)

        if not resp.candidates or not resp.candidates[0].content.parts:
            break

        model_parts = resp.candidates[0].content.parts
        history.append(types.Content(role="model", parts=model_parts))

        tool_calls = []
        turn_text = ""
        for part in model_parts:
            if hasattr(part, "thought") and part.thought:
                steps.append({"type": "thought", "content": str(part.thought)})
            if part.function_call:
                call = part.function_call
                tool_calls.append(call)
                steps.append({"type": "call", "name": call.name, "args": dict(call.args)})
                logger.info(f"[Agent] Yêu cầu gọi tool: {call.name} với args: {dict(call.args)}")
            if part.text:
                turn_text += part.text

        if not tool_calls:
            logger.info(f"[Agent] Dừng vòng lặp tại Turn {turn_idx + 1}. Agent đã đưa ra câu trả lời cuối cùng.")
            pre_think, parsed_answer = parse_agent_response(turn_text)
            if pre_think:
                steps.append({"type": "reasoning", "content": pre_think})
            final_answer = parsed_answer
            break
        else:
            if turn_text:
                steps.append({"type": "reasoning", "content": turn_text})

        tool_response_parts = []
        for call in tool_calls:
            try:
                tool_func = tool_map.get(call.name)
                result = (
                    await tool_func(**call.args)
                    if tool_func
                    else f"Error: Tool {call.name} not found."
                )
                logger.debug(f"[Agent] Kết quả tool {call.name}: {str(result)[:200]}...")
                steps.append({"type": "tool_output", "name": call.name, "output": str(result)})
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"result": result})
                )
            except Exception as e:
                logger.error(f"Error executing tool {call.name}: {e}")
                tool_response_parts.append(
                    types.Part.from_function_response(name=call.name, response={"error": str(e)})
                )

        history.append(types.Content(role="user", parts=tool_response_parts))

    sources_data = await build_sources_from_steps(steps, candidate_files)
    final_answer = verify_citations(final_answer, sources_data)

    return {
        "final_answer": final_answer,
        "steps": steps,
        "sources": sources_data,
        "tokenUsage": {
            "promptTokens": total_prompt_tokens,
            "completionTokens": total_candidates_tokens,
            "totalTokens": total_prompt_tokens + total_candidates_tokens
        }
    }

"""
Shared RAG Agent logic: Prompt and Tools for Gemini GenAI.
Used by both Chat and Email Inquiry services.
"""
import logging
import time
from typing import List, Callable, Dict, Any, Optional
from app.integrations.pageindex.client import get_page_index_client
import re
import difflib
from app.integrations.storage.client import r2_storage
from app.core.config import settings
from app.integrations.llm.gemini import gemini_client
from google.genai import types
from app.utils.format_utils import sanitize_latex_in_markdown

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """
Bạn là tư vấn viên chính thức của Phòng Giáo vụ trường đại học.
Bạn được trang bị tự động các công cụ để tìm kiếm và đọc tài liệu quy chế, thủ tục thông qua chỉ mục cấu trúc.
Người dùng sẽ cung cấp danh sách các file_id tài liệu liên quan đến câu hỏi.

QUY TRÌNH SỬ DỤNG CÔNG CỤ:
1. TRƯỚC KHI GỌI CÔNG CỤ: Mọi kế hoạch, suy nghĩ, lập luận (reasoning/plan) trước khi bạn quyết định gọi công cụ BẮT BUỘC PHẢI DÙNG TIẾNG VIỆT tĩnh tại (Ví dụ: "Người dùng đang hỏi về điều kiện... Mình cần tìm..."). Tuyệt đối không dùng tiếng Anh.
2. Hãy dùng công cụ `get_document_structure(file_id)` để xem mục lục của tài liệu. Bạn chỉ được phép sử dụng các `file_id` hoặc số thứ tự tài liệu [n] (ví dụ: '1') đã được cung cấp trong danh sách ứng viên.
3. Dùng công cụ `get_page_content(file_id, pages="start_line-end_line")` để đọc nội dung chi tiết. Đây là bước bắt buộc để có dữ liệu chính xác trước khi trả lời.
4. Bạn có thể gọi các công cụ này nhiều lần cho các tài liệu khác nhau nếu cần thiết. Luôn ưu tiên dùng số thứ tự [n] để gọi tool cho chính xác.

QUY TẮC CÂU TRẢ LỜI CUỐI CÙNG CHO NGƯỜI DÙNG:
- KHI DỪNG GỌI CÔNG CỤ ĐỂ TRẢ LỜI: Bạn BẮT BUỘC phải bọc toàn bộ nội dung hướng dẫn chi tiết dành cho sinh viên bên trong cặp thẻ XML `<answer>` và `</answer>`.
- Mọi suy nghĩ, lập luận rút ra, báo cáo trung gian ("Tôi đã tìm thấy...", "Từ tài liệu...", "Tôi có đủ thông tin...") BẮT BUỘC phải viết bên ngoài, TRƯỚC thẻ `<answer>`.
- Luôn xưng hô chuyên nghiệp là "Phòng Giáo vụ" hoặc "chúng tôi" ở trong phần `<answer>`.
- TUYỆT ĐỐI KHÔNG DÙNG CÂU CHÀO (không dùng "Chào bạn", "Xin chào"). Đi thẳng vào nội dung tư vấn ngay lập tức.
- YÊU CẦU TRÍCH DẪN: Ngay sau khi bạn đã **dùng xong toàn bộ thông tin cần thiết từ một mục/điều của tài liệu** và không cần tham chiếu thêm đến mục đó nữa, BẮT BUỘC chèn ngay tham chiếu bằng cú pháp: `(^Tên mục lục tương ứng)` (Ví dụ: `(^Điều 2: Điều kiện xét tốt nghiệp)`). Đây là tín hiệu "Tôi đã xong với mục này". KHÔNG chèn ở từng câu riêng lẻ.
- Định dạng nội dung: Nội dung bên trong `<answer>` PHẢI sử dụng định dạng Markdown (như **in đậm** để nhấn mạnh các ý quan trọng, sử dụng danh sách liệt kê `-` hoặc `1.` để trình bày các bước/điều kiện một cách rõ ràng).
- Định dạng chuẩn:
[Những suy nghĩ nháp không gửi cho sinh viên]
<answer>
[Nội dung tư vấn bằng Markdown, đi thẳng vào trọng tâm, không chào hỏi]
</answer>
- KHÔNG để lộ `file_id` hoặc chi tiết hệ thống với sinh viên. Khi cần trích dẫn, hãy nhắc tên tệp được cung cấp phía trên.
- TUYỆT ĐỐI KHÔNG nhắc đến tên các thẻ XML (như <answer>) trong phần suy nghĩ/lập luận của bạn.
- Nếu không tìm thấy thông tin trong tài liệu, hãy nói rõ: "Hệ thống không tìm thấy quy định này trong tài liệu hiện có." và đề nghị sinh viên liên hệ trực tiếp văn phòng.
"""

def build_pindex_tools(candidate_files: List[dict]) -> List[Callable]:
    """Create bound tool instances so LLM can invoke PageIndex client."""
    client = get_page_index_client()
    allow_ids = [c["file_id"] for c in candidate_files]

    def resolve_file_id(fid: str) -> str:
        """Resolve a file_id which could be a long hex string or a numeric index string like '1'."""
        if not isinstance(fid, str):
            fid = str(fid)
        fid = fid.strip().strip('[]')
        # Try numeric index first
        if fid.isdigit():
            idx = int(fid) - 1
            if 0 <= idx < len(candidate_files):
                return candidate_files[idx]["file_id"]
        return fid

    async def get_document_structure(file_id: str) -> str:
        """
        Get the hierarchical table of contents (structure) for a document. 
        Args:
            file_id: The unique identifier of the file/document (or numeric index like '1').
        """
        real_id = resolve_file_id(file_id)
        if real_id not in allow_ids:
            msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
            logger.warning(f"[Agent] {msg}")
            return f'{{"error": "Tài liệu \'{file_id}\' không hợp lệ. Hãy dùng số thứ tự [n] trong danh sách được cung cấp."}}'
        
        file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
        logger.info(f"[Agent] Tool call: get_document_structure(file_id='{file_id}') -> Resolved to ID: {real_id} (File: {file_name})")
        return await client.get_document_structure(real_id)

    async def get_page_content(file_id: str, pages: str) -> str:
        """
        Get the actual text content of specific sections or line ranges.
        Args:
            file_id: The unique identifier of the file/document (or numeric index like '1').
            pages: A string representing line ranges or page numbers (e.g., '10-20', '5,8').
        """
        real_id = resolve_file_id(file_id)
        if real_id not in allow_ids:
            msg = f"Agent requested invalid file_id: {file_id} (Resolved: {real_id}). Allowed IDs: {allow_ids}"
            logger.warning(f"[Agent] {msg}")
            return f'{{"error": "Tài liệu \'{file_id}\' không hợp lệ. Hãy dùng số thứ tự [n] trong danh sách được cung cấp."}}'
        
        file_name = next((c["file_name"] for c in candidate_files if c["file_id"] == real_id), "Unknown")
        logger.info(f"[Agent] Tool call: get_page_content(file_id='{file_id}', pages='{pages}') -> Resolved to ID: {real_id} (File: {file_name})")
        return await client.get_page_content(real_id, pages)

    return [get_document_structure, get_page_content]


def parse_agent_response(text: str) -> tuple[str, str]:
    """
    Parse the agent's text response to separate reasoning (pre-thought) and the final answer.
    Looks for the LAST <answer>...</answer> tags for robust parsing.
    Returns:
        tuple: (reasoning_text, final_answer_text)
    """

    # Strip common Gemini thinking artifacts
    text = re.sub(r"^`\.\n?", "", text).strip()
    
    # 1. Try to find the last valid <answer>...</answer> block
    matches = list(re.finditer(r'<answer>(.*?)</answer>', text, flags=re.DOTALL | re.IGNORECASE))
    if matches:
        last_match = matches[-1]
        pre_think = text[:last_match.start()].strip()
        answer = last_match.group(1).strip()
        return pre_think, answer
        
    # 2. Try to find the last <answer> tag if no closing tag exists (truncation case)
    all_opens = list(re.finditer(r'<answer>', text, flags=re.IGNORECASE))
    if all_opens:
        last_open = all_opens[-1]
        pre_think = text[:last_open.start()].strip()
        answer = text[last_open.end():].strip()
        return pre_think, answer
        
    # 3. Fallback: return everything as answer
    return "", text.strip()


def verify_citations(
    text: str,
    sources_data: list[dict],
    resolve_citations: bool = False,
    citation_link_type: str = "original",  # "original" | "markdown"
) -> str:
    """Verify and optionally resolve citation markers."""
    valid_titles = [s["title"] for s in sources_data if s.get("title")]

    def _find_source_for_title(raw_title: str) -> dict | None:
        """Return the best-matching source dict for a given raw title."""
        for s in sources_data:
            vt = s.get("title", "")
            if raw_title.lower() in vt.lower() or vt.lower() in raw_title.lower():
                return s
        matches = difflib.get_close_matches(raw_title, [s.get("title", "") for s in sources_data], n=1, cutoff=0.6)
        if matches:
            for s in sources_data:
                if s.get("title") == matches[0]:
                    return s
        return None

    def verify_title(match):
        raw_title = match.group(1).strip()
        source = _find_source_for_title(raw_title)
        if not source:
            return ""

        verified_title = source.get("title", raw_title)

        if resolve_citations:
            if citation_link_type == "markdown":
                url = source.get("markdown_url", "")
            else:
                url = source.get("original_url", "")

            if url:
                return f"(Xem thêm tại [{verified_title}]({url}))"
            else:
                return f"(^{verified_title})"
        else:
            return f"(^{verified_title})"

    if not text or not valid_titles:
        return re.sub(r'\(\^(.*?)\)', "", text) if text else text

    return re.sub(r'\(\^(.*?)\)', verify_title, text)


class CitationStreamFormatter:
    def __init__(
        self,
        sources_data: list[dict],
        resolve_citations: bool = False,
        citation_link_type: str = "markdown",
    ):
        self.sources_data = sources_data
        self.resolve_citations = resolve_citations
        self.citation_link_type = citation_link_type
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

                     processed = verify_citations(ready_part, self.sources_data, self.resolve_citations, self.citation_link_type)
                     self.buffer = pending_part
                     return processed

        processed = verify_citations(self.buffer, self.sources_data, self.resolve_citations, self.citation_link_type)
        self.buffer = ""
        return processed

    def flush(self) -> str:
        processed = verify_citations(self.buffer, self.sources_data, self.resolve_citations, self.citation_link_type)
        self.buffer = ""
        return processed


async def build_sources_from_steps(
    steps: list[dict],
    candidate_files: list[dict],
) -> list[dict]:
    """
    Build source citation list from actual agent tool calls.
    """
    file_map = {c["file_id"]: c for c in candidate_files}

    # file_id -> ordered unique list of access markers (pages or 'structure')
    accessed: dict[str, list[str]] = {}
    for step in steps:
        if step.get("type") == "call":
            name = step.get("name")
            args = step.get("args") or {}
            # Handle both numeric ref IDs and full hex IDs
            raw_fid = args.get("file_id")
            if raw_fid:
                raw_fid = str(raw_fid).strip().strip('[]')
                if raw_fid.isdigit():
                    idx = int(raw_fid) - 1
                    if 0 <= idx < len(candidate_files):
                        file_id = candidate_files[idx]["file_id"]
                    else:
                        file_id = raw_fid
                else:
                    file_id = raw_fid
                
                if file_id in file_map:
                    if file_id not in accessed:
                        accessed[file_id] = []
                    
                    if name == "get_page_content":
                        pages = args.get("pages", "")
                        if pages and pages not in accessed[file_id]:
                            accessed[file_id].append(pages)
                    elif name == "get_document_structure":
                        pass

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
    targets = accessed.items() if accessed else [] # Only show files actually read
    
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
            "pages": pages_list if pages_list else None,
            "original_url": orig_url,
            "markdown_url": md_url
        })

    return sources


def get_agent_config(candidate_files: list[dict]) -> tuple[list[Callable], dict[str, Callable], Any]:
    """
    Build tools, map, and GenerateContentConfig for the RAG agent.
    """
    tools = build_pindex_tools(candidate_files)
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
    resolve_citations: bool = False,
    citation_link_type: str = "original",
) -> dict:
    """
    Run the manual PageIndex agent loop and return a structured result.
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
        start_gen = time.perf_counter()
        resp = await gemini_client.client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=history,
            config=config,
        )
        gen_dur = time.perf_counter() - start_gen
        logger.info(f"[Agent] Gemini generation Turn {turn_idx + 1} completed in {gen_dur:.2f}s")

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
                start_tool = time.perf_counter()
                result = (
                    await tool_func(**call.args)
                    if tool_func
                    else f"Error: Tool {call.name} not found."
                )
                tool_dur = time.perf_counter() - start_tool
                logger.info(f"[Agent] Tool {call.name} completed in {tool_dur:.2f}s")
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
    final_answer = verify_citations(final_answer, sources_data, resolve_citations, citation_link_type)
    final_answer = sanitize_latex_in_markdown(final_answer)

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

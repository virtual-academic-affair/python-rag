"""Inquiry workflow service: RAG reply generation using RetrievalService."""
import logging
from typing import Dict, Any, Optional, List

from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings
from app.integrations.llm.gemini import build_chat_llm, build_extraction_llm, chain_prompt
from app.integrations.grpc.client import get_grpc_client
from app.modules.retrieval.service import get_retrieval_service
from app.modules.email.utils import extract_structured_data, remove_accents, extract_inquiry_filters
from app.modules.metadata.service import get_metadata_service
from app.modules.email.schemas import InquiryIntent, InquiryTypesResult, InquiryFilters

logger = logging.getLogger(__name__)

class InquiryService:
    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._extraction_llm = build_extraction_llm(
            api_key=settings.GOOGLE_API_KEY,
            model=settings.GEMINI_MODEL,
            temperature=0.0
        )
        
        self.intent_prompt = ChatPromptTemplate.from_messages([
            ("system", "Trích xuất câu hỏi chính hoặc ý định của người dùng từ email dưới đây bằng tiếng Việt. Trả về JSON theo schema: {{\"question\": string}}"),
            ("human", "Tiêu đề: {title}\nNội dung:\n{content}")
        ])
        
        self.types_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "Phân loại email hỏi đáp dưới đây thành các mảng/loại thắc mắc.\n"
                "Chỉ chọn: 'graduation', 'training', 'procedure'. Nếu không rõ, chọn 'training'.\n"
                "Trả về JSON: {{\"inquiry_types\": [string]}}"
            )),
            ("human", "Tiêu đề: {title}\nNội dung:\n{content}")
        ])
        self._metadata_svc = get_metadata_service()

    async def process(
        self,
        title: str,
        content: str,
        message_id: Optional[int] = None,
        user_role: str = "student",
    ) -> Dict[str, Any]:
        """
        Inquiry Workflow:
        1. Extract Intent & Types via Gemini.
        2. Extract Filters (Future: can be Gemini or Rule-based).
        3. Retrieve Answer via RetrievalService (RAG).
        4. (Optional) Create Gmail Draft.
        """
        # 1. Extraction
        intent_data = await extract_structured_data(self._extraction_llm, self.intent_prompt, {"title": title, "content": content})
        extracted_question = intent_data.get("question")
        
        types_data = await extract_structured_data(self._extraction_llm, self.types_prompt, {"title": title, "content": content})
        inquiry_types = types_data.get("inquiry_types", ["training"])

        # 2. Filter Extraction (Rule-based)
        inquiry_filters = await extract_inquiry_filters(title, content, self._metadata_svc)
        metadata_filter = {}
        if inquiry_filters:
            metadata_filter = inquiry_filters.model_dump(exclude_none=True)
            logger.info(f"Extracted inquiry filters: {metadata_filter}")
        
        # 3. RAG Step
        rag_query = extracted_question or f"{title}\n{content}"
        
        # Retrieval Step
        candidate_files = await self._retrieval.retrieve_candidate_files(
            query=rag_query,
            metadata_filter=metadata_filter,
            user_role=user_role
        )
        
        if not candidate_files:
            rag_result = {"answer": "Không tìm thấy tài liệu phù hợp để trả lời email này.", "sources": []}
        else:
            candidate_ids = [c["file_id"] for c in candidate_files]
            
            # 3. Prepare Context Prompt (Enriched with Metadata)
            files_info_str = "\n".join([
                f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}" 
                for c in candidate_files
            ])
            
            # Enrich prompt with metadata context if available
            context_blocks = []
            if metadata_filter.get("academic_year"):
                context_blocks.append(f"Academic Year: {metadata_filter['academic_year']}")
            if metadata_filter.get("cohort"):
                context_blocks.append(f"Cohort: {metadata_filter['cohort']}")
            
            context_str = f"Context Information: [{', '.join(context_blocks)}]\n\n" if context_blocks else ""

            prompt_text = (
                f"Email Subject: {title}\n"
                f"Email Body:\n{content}\n\n"
                f"{context_str}"
                f"Relevant documents found:\n{files_info_str}\n\n"
                f"Please answer the user's specific inquiry based on these documents. Respect the specific rules for the given academic year and cohort if provided."
            )

            # Generate Answer using shared Agent logic
            from app.modules.retrieval.agent import AGENT_SYSTEM_PROMPT, build_pindex_tools
            from app.integrations.llm.gemini import gemini_client
            from google.genai import types

            tools = build_pindex_tools(candidate_ids)
            config = types.GenerateContentConfig(
                system_instruction=AGENT_SYSTEM_PROMPT,
                tools=tools,
                temperature=0.0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=5)
            )

            resp = await gemini_client.client.aio.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt_text,
                config=config
            )
            
            # Format sources
            formatted_sources = []
            for i, c in enumerate(candidate_files):
                formatted_sources.append({
                    "citation_id": i + 1,
                    "title": c.get("file_name", ""),
                    "file_id": c.get("file_id"),
                    "text": c.get("doc_description", "")
                })

            rag_result = {
                "answer": resp.text or "Xin lỗi, tôi không thể tìm thấy câu trả lời chính xác.",
                "sources": formatted_sources
            }

        logger.info(f"Inquiry RAG complete. Answer length: {len(rag_result['answer'])}")

        # 4. Integrate with Gmail Draft creation if message_id exists
        if message_id is not None:
            try:
                grpc = get_grpc_client()
                await grpc.create_inquiry(
                    message_id=message_id,
                    answer=rag_result["answer"],
                    extracted_question=extracted_question,
                    inquiry_types=inquiry_types,
                    sources=rag_result["sources"]
                )
            except Exception as e:
                logger.warning(f"Failed to create Gmail draft via gRPC: {e}")

        return {
            "answer": rag_result["answer"],
            "sources": rag_result["sources"],
            "question": extracted_question,
            "types": inquiry_types,
            "filters": metadata_filter,
            "message_id": message_id
        }


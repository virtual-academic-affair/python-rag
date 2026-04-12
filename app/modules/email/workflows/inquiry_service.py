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
            # Expand each filter value to include "all" so documents tagged
            # with "all" are always included in RAG results.
            # e.g. {"academic_year": "2024-2025"} -> {"academic_year": ["2024-2025", "all"]}
            raw_filters = inquiry_filters.model_dump(exclude_none=True)
            for k, v in raw_filters.items():
                if v:
                    metadata_filter[k] = [v, "all"]
            logger.info(f"Extracted and expanded inquiry filters: {metadata_filter}")
        
        # 3. RAG Step
        rag_query = extracted_question or f"{title}\n{content}"
        
        from app.modules.chat.service import get_chat_service
        from app.modules.chat.schemas import UserContext
        
        chat_svc = get_chat_service()
        user_context = UserContext(
            user_id=str(message_id) if message_id else "manual_inquiry",
            name="Inquiry System",
            cohort="N/A",
            role=user_role
        )
        
        rag_result = await chat_svc.generate_chat_response(
            question=rag_query,
            user_context=user_context,
            chat_history=[],
            metadata_filter=metadata_filter
        )

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


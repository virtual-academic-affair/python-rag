"""Inquiry workflow service: RAG reply generation using RetrievalService."""
import logging
from typing import Dict, Any, Optional, List

from langchain_core.prompts import ChatPromptTemplate
from app.core.config import settings
from app.integrations.llm.gemini import build_extraction_llm
from app.modules.rag.retrieval.service import get_retrieval_service
from app.modules.metadata.extraction import extract_metadata_from_text
from app.modules.email.utils import extract_structured_data
from app.modules.faq.service import get_faq_service
import asyncio

logger = logging.getLogger(__name__)

class InquiryService:
    def __init__(self):
        self._retrieval = get_retrieval_service()
        self._extraction_llm = build_extraction_llm(
            api_key=settings.GOOGLE_API_KEY,
            model=settings.GEMINI_MODEL,
            temperature=0.0
        )
        
        # Unified prompt for extracting both intent and types in one call
        self.extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "Bạn là chuyên gia phân tích email giáo vụ. Hãy phân tích email dưới đây để trích xuất dữ liệu sau:\n"
                "1. 'question': Câu hỏi chính hoặc ý định cốt lõi của người dùng (trình bày ngắn gọn bằng tiếng Việt).\n"
                "2. 'inquiry_types': Danh sách các loại thắc mắc (chọn từ: ['graduation', 'training']).\n"
                "   - 'graduation': Các vấn đề liên quan đến tốt nghiệp, xét tốt nghiệp, chứng nhận, bằng cấp.\n"
                "   - 'training': Các vấn đề về đào tạo, học phần, đăng ký học tập, thời khóa biểu, điểm số, học vụ.\n"
                "   - Nếu không rõ ràng hoặc thuộc loại khác, mặc định chọn ['training'].\n"
                "\nTrả về DUY NHẤT một đối tượng JSON theo schema: "
                "{{\"question\": string, \"inquiry_types\": [string]}}"
            )),
            ("human", "Tiêu đề: {title}\nNội dung:\n{content}")
        ])

    async def process(
        self,
        title: str,
        content: str,
        message_id: Optional[int] = None,
        user_role: str = "student",
    ) -> Dict[str, Any]:
        """
        Inquiry Workflow:
        1. Unified Extraction (Intent & Types) via Gemini.
        2. Filter Extraction from full context.
        3. Retrieve Answer via RetrievalService (RAG).
        """
        # 1. Unified Extraction (Call LLM only once)
        extraction_data = await extract_structured_data(
            self._extraction_llm, 
            self.extraction_prompt, 
            {"title": title, "content": content}
        )
        extracted_question = extraction_data.get("question")
        inquiry_types = extraction_data.get("inquiry_types", ["training"])

        # 2. Filter Extraction (Rule-based from original email context)
        metadata_filter = await extract_metadata_from_text(f"{title} {content}")
        
        # 3. RAG Step
        rag_query = extracted_question or f"{title}\n{content}"
        faq_svc = await get_faq_service()
        
        # [NEW] FAQ Pre-check: Semantic search before full RAG
        question_vector = await faq_svc.embed(rag_query)
        faq = await faq_svc.find_best_match(question_vector, metadata_filter)
        
        if faq:
            processing_time_ms = 0 # Approximate for now, or track it
            logger.info(f"[Inquiry] FAQ hit: '{faq['question']}'")
            rag_result = {
                "answer": faq["answer_markdown"],
                "sources": [],
                "source": "faq"
            }
        else:
            # Retrieval Step
            candidate_files = await self._retrieval.retrieve_candidate_files(
                query=rag_query,
                metadata_filter=metadata_filter,
                user_role=user_role
            )
            
            if not candidate_files:
                rag_result = {
                    "answer": "Không tìm thấy tài liệu phù hợp để trả lời email này.", 
                    "sources": [],
                    "source": "bypass"
                }
            else:
                # Prepare Context Prompt (Enriched with Metadata)
                files_info_str = "\n".join([
                    f"- ID: {c['file_id']} | Name: {c['file_name']} | Description: {c.get('doc_description', '')}" 
                    for c in candidate_files
                ])
                
                # Enrich prompt with metadata context if available
                context_blocks = []
                if metadata_filter.get("academic_year"):
                    ay = metadata_filter["academic_year"]
                    context_blocks.append(f"Academic Year: {ay.get('fromYear')}-{ay.get('toYear')}")
                if metadata_filter.get("enrollment_year"):
                    ey = metadata_filter["enrollment_year"]
                    context_blocks.append(f"Enrollment Year: {ey.get('fromYear')}-{ey.get('toYear')}")
                
                context_str = f"Context Information: [{', '.join(context_blocks)}]\n\n" if context_blocks else ""

                prompt_text = (
                    f"Email Subject: {title}\n"
                    f"Email Body:\n{content}\n\n"
                    f"{context_str}"
                    f"Relevant documents found:\n{files_info_str}\n\n"
                    f"Please answer the user's specific inquiry based on these documents. Respect the specific rules for the given academic year and cohort if provided."
                )

                # Generate Answer using shared Agent logic
                from app.modules.rag.retrieval.agent import run_agent_loop

                agent_result = await run_agent_loop(
                    candidate_files=candidate_files,
                    prompt_contents=prompt_text,
                    resolve_citations=True,
                    citation_link_type="original",
                )

                rag_result = {
                    "answer": agent_result["final_answer"] or "Xin lỗi, tôi không thể tìm thấy câu trả lời chính xác.",
                    "sources": agent_result["sources"],
                    "source": "llm"
                }

        logger.info(f"Inquiry flow complete. Source: {rag_result.get('source')}. Answer length: {len(rag_result['answer'])}")
        
        # Log async interaction
        if not faq: # Only log if it wasn't already an FAQ hit to avoid duplicate logs if needed, or always log for analytics
            asyncio.create_task(faq_svc.log_interaction(
                question=rag_query,
                question_vector=question_vector,
                answer_markdown=rag_result["answer"],
                metadata_filter=metadata_filter,
                source_type="inquiry_email",
                email_message_id=message_id,
            ))

        return {
            "answer": rag_result["answer"],
            "sources": rag_result["sources"],
            "source": rag_result.get("source"),
            "question": extracted_question,
            "types": inquiry_types,
            "filters": metadata_filter,
            "message_id": message_id
        }

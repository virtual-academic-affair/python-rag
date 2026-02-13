"""LangChain service for classification and routing to specific services"""
import logging
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import InternalData, ResponseModel
from app.services.domain.class_registration_service import ClassRegistrationService
from app.services.domain.administrative_service import AdministrativeService
from app.services.domain.graduation_service import GraduationService
from app.services.domain.academic_programme_service import AcademicProgrammeService
from app.services.domain.department_service import DepartmentService
from app.services.domain.other_service import OtherService
from app.services.orchestration.llm_factory import build_classification_llm, chain_prompt, env_thinking_level

logger = logging.getLogger(__name__)


class LangChainClassifier:
    """LangChain classifier for student email classification and data extraction"""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        temperature: float = 0.1,
    ):
        from config.settings import settings

        resolved_model = model or settings.LLM_MODEL
        self.llm = build_classification_llm(
            api_key=api_key,
            model=resolved_model,
            temperature=temperature,
            thinking_level=env_thinking_level(),
        )

        self.classification_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content="""You are an expert at classifying Vietnamese student emails.
Classify the email into EXACTLY ONE of these categories:

- class_registration
- administrative
- graduation
- academic_programme
- department
- other

HARD RULES (highest priority):
- If the email requests to register/enroll for a course or class, it MUST be class_registration.
- Any occurrence of these phrases implies class_registration:
  * "đăng ký học phần" / "đăng ký lớp học phần" / "xin đăng ký" / "yêu cầu đăng ký"
  * "mã học phần" / "mã môn" / "mã lớp" / "lớp học phần"
  * English: "enroll" / "register for" / "add class"
- Do NOT classify such emails as academic_programme even if they mention "môn học".

Guidance:
- academic_programme is for questions about grades, curriculum, study plan, academic policies, instructor issues.

Return ONLY the category name, nothing else."""
                ),
                HumanMessage(content="Title: {title}\n\nContent: {content}"),
            ]
        )

        self.class_registration_service = ClassRegistrationService(self.llm)
        self.administrative_service = AdministrativeService()
        self.graduation_service = GraduationService()
        self.academic_programme_service = AcademicProgrammeService()
        self.department_service = DepartmentService()
        self.other_service = OtherService()

    async def classify_request(self, title: str, content: str) -> str:
        try:
            chain = chain_prompt(self.classification_prompt, self.llm)
            result = await chain.ainvoke({"title": title, "content": content})
            classification = result.content.strip().lower()

            valid = {
                "class_registration",
                "administrative",
                "graduation",
                "academic_programme",
                "department",
                "other",
            }
            if classification not in valid:
                logger.warning(
                    "Invalid classification: %s, defaulting to 'other'", classification
                )
                return "other"
            return classification
        except Exception as e:
            logger.error("Error in classification: %s", str(e))
            return "other"

    async def process_request(
        self, internal_data: InternalData, title: str, content: str
    ) -> ResponseModel:
        try:
            logger.info("Starting classification...")
            classification = await self.classify_request(title, content)
            logger.info("Classification result: %s", classification)

            combined_text = (title + " " + content).lower()
            class_registration_keywords = [
                "đăng ký lớp học phần",
                "đăng ký lớp",
                "đăng ký môn học",
                "đăng ký học phần",
                "hủy lớp",
                "rút lớp",
                "đổi lớp",
                "yêu cầu đăng ký",
                "yêu cầu hủy",
                "yêu cầu đổi",
                "mã lớp",
                "môn học",
                "lớp học phần",
                "enroll",
                "register for class",
                "cancel class",
                "change class",
            ]
            is_class_registration = any(k in combined_text for k in class_registration_keywords)
            if classification != "class_registration" and is_class_registration:
                logger.warning(
                    "Classification was %r but keywords detected; overriding to 'class_registration'",
                    classification,
                )
                classification = "class_registration"

            if classification == "class_registration":
                logger.info("Routing -> class_registration_service")
                return await self.class_registration_service.process(
                    internal_data, title, content
                )

            if classification == "administrative":
                logger.info("Routing -> administrative_service")
                return await self.administrative_service.process(internal_data, title, content)
            if classification == "graduation":
                logger.info("Routing -> graduation_service")
                return await self.graduation_service.process(internal_data, title, content)
            if classification == "academic_programme":
                logger.info("Routing -> academic_programme_service")
                return await self.academic_programme_service.process(internal_data, title, content)
            if classification == "department":
                logger.info("Routing -> department_service")
                return await self.department_service.process(internal_data, title, content)

            logger.info("Routing -> other_service")
            return await self.other_service.process(internal_data, title, content)

        except Exception as e:
            logger.error("Error processing request: %s", str(e), exc_info=True)
            return await self.other_service.process(internal_data, title, content)


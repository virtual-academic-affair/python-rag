"""LangChain service for classification and routing to specific services"""
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from app.models.schemas import InternalData, ResponseModel
from app.services.class_registration_service import ClassRegistrationService
from app.services.administrative_service import AdministrativeService
from app.services.graduation_service import GraduationService
from app.services.academic_programme_service import AcademicProgrammeService
from app.services.department_service import DepartmentService
from app.services.other_service import OtherService

logger = logging.getLogger(__name__)


class LangChainClassifier:
    """LangChain classifier for student email classification and data extraction"""
    
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash-lite", temperature: float = 0.1):
        """
        Initialize LangChain classifier.
        
        Args:
            api_key: Google API key for Gemini
            model: Model name to use (default: "gemini-2.5-flash-lite")
            temperature: Temperature for model responses (default: 0.1)
        """
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature,
            convert_system_message_to_human=True
        )
        
        self.classification_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content="""You are an expert at classifying student emails and requests. 
            Analyze the provided email title and content and classify it into one of these categories:
            
            - class_registration: For requests related to registering for classes, enrolling in courses, signing up for class sections, canceling classes, changing classes.
              Keywords: "đăng ký lớp học phần", "đăng ký lớp", "đăng ký môn học", "hủy lớp", "rút lớp", "đổi lớp", 
                        "yêu cầu đăng ký", "yêu cầu hủy", "yêu cầu đổi lớp", "mã lớp", "môn học",
                        "enroll", "register for class", "cancel class", "change class"
              Examples: "Đăng ký lớp học phần", "Xin đăng ký lớp", "Hủy lớp học phần", "Đổi lớp", 
                        "Yêu cầu đăng ký, hủy và đổi lớp học phần"
              IMPORTANT: If the email title or content mentions "đăng ký", "hủy", "đổi" together with "lớp học phần" or "mã lớp" or "môn học", 
                         it MUST be classified as "class_registration"
            
            - administrative: For general administrative matters, document requests, certificates, official documents, paperwork.
              Keywords: "cấp bản sao", "giấy tờ", "chứng chỉ", "đơn từ", "thủ tục hành chính", "document request", "certificate", "transcript copy"
              Examples: "Yêu cầu cấp bản sao bảng điểm", "Xin giấy chứng nhận", "Thủ tục hành chính"
            
            - graduation: For graduation-related requests, thesis defense, final projects, graduation ceremony.
              Keywords: "tốt nghiệp", "bảo vệ khóa luận", "bảo vệ đồ án", "graduation", "thesis defense", "final project"
              Examples: "Đăng ký bảo vệ khóa luận tốt nghiệp", "Yêu cầu tốt nghiệp"
            
            - academic_programme: For academic issues, grade inquiries, academic policies, study plans, curriculum questions, course-related questions, instructor-related issues.
              Keywords: "điểm số", "học vụ", "chương trình học", "môn học", "giảng viên", "grades", "academic policies", "curriculum", "course", "instructor"
              Examples: "Xin giải thích về điểm số", "Thắc mắc về chương trình học", "Vấn đề với giảng viên"
            
            - department: For requests from other departments (PDT, PKT) sending transcripts, grade appeals, etc. to students.
              Keywords: "phòng đào tạo", "phòng khảo thí", "PDT", "PKT", "bảng điểm", "đơn phúc khảo", "department", "transcript", "grade appeal"
              Examples: "PDT gửi bảng điểm", "PKT gửi đơn phúc khảo"
            
            - other: For anything that doesn't fit the above categories.
            
            IMPORTANT: 
            - If the email is about registering/enrolling in a specific class or course (đăng ký lớp học phần), 
              it MUST be classified as "class_registration", NOT "academic_programme".
            - If the email is about administrative paperwork or documents, classify as "administrative".
            - If the email is about academic issues, courses, instructors, classify as "academic_programme".
            
            Respond with ONLY the category name, nothing else."""),
            HumanMessage(content="Title: {title}\n\nContent: {content}")
        ])
        
        # Initialize services
        self.class_registration_service = ClassRegistrationService(self.llm)
        self.administrative_service = AdministrativeService()
        self.graduation_service = GraduationService()
        self.academic_programme_service = AcademicProgrammeService()
        self.department_service = DepartmentService()
        self.other_service = OtherService()
        

    async def classify_request(self, title: str, content: str) -> str:
        """Classify the request into one of the predefined categories."""
        try:
            chain = self.classification_prompt | self.llm
            result = await chain.ainvoke({
                "title": title,
                "content": content
            })
            
            classification = result.content.strip().lower()
            
            # Validate classification
            valid_classifications = [
                "class_registration", "administrative", 
                "graduation", "academic_programme", "department", "other"
            ]
            
            if classification not in valid_classifications:
                logger.warning(f"Invalid classification: {classification}, defaulting to 'other'")
                return "other"
                
            return classification
            
        except Exception as e:
            logger.error(f"Error in classification: {str(e)}")
            return "other"


    async def process_request(
        self, 
        internal_data: InternalData, 
        title: str, 
        content: str
    ) -> ResponseModel:
        """Process the complete request and return appropriate response."""
        try:
            # First, classify the request
            logger.info("Starting classification...")
            classification = await self.classify_request(title, content)
            logger.info(f"Classification result: {classification}")
            
            # Fallback: Check if it's actually a class registration request
            # even if classification was wrong
            class_registration_keywords = [
                "đăng ký lớp học phần", "đăng ký lớp", "đăng ký môn học",
                "đăng ký học phần", "hủy lớp", "rút lớp", "đổi lớp",
                "yêu cầu đăng ký", "yêu cầu hủy", "yêu cầu đổi",
                "mã lớp", "môn học", "lớp học phần",
                "enroll", "register for class", "cancel class", "change class"
            ]
            combined_text = (title + " " + content).lower()
            is_class_registration = any(keyword.lower() in combined_text for keyword in class_registration_keywords)
            
            logger.info(f"Fallback check - is_class_registration: {is_class_registration}, classification: {classification}")
            if is_class_registration:
                logger.info(f"Detected class registration keywords in: {title[:50]}...")
            
            if classification != "class_registration" and is_class_registration:
                logger.warning(f"Classification was '{classification}' but detected class registration keywords, overriding to 'class_registration'")
                classification = "class_registration"
            elif classification == "other" and is_class_registration:
                logger.warning(f"Classification returned 'other' but keywords detected, forcing 'class_registration'")
                classification = "class_registration"
            
            # Route to appropriate service
            if classification == "class_registration":
                try:
                    return await self.class_registration_service.process(internal_data, title, content)
                except Exception as e:
                    logger.error(f"Error in class_registration_service: {str(e)}", exc_info=True)
                    # Re-raise to be caught by outer handler, but log the error first
                    raise
            elif classification == "administrative":
                return await self.administrative_service.process(internal_data, title, content)
            elif classification == "graduation":
                return await self.graduation_service.process(internal_data, title, content)
            elif classification == "academic_programme":
                return await self.academic_programme_service.process(internal_data, title, content)
            elif classification == "department":
                return await self.department_service.process(internal_data, title, content)
            else:
                return await self.other_service.process(internal_data, title, content)
                
        except Exception as e:
            logger.error(f"Error processing request: {str(e)}", exc_info=True)
            # Only return "other" if it's not a class_registration classification error
            # If classification was class_registration but extraction failed, we should still return error
            # For now, return other as fallback, but log the issue
            logger.error(f"Falling back to 'other' service due to error. Original classification may have been incorrect.")
            return await self.other_service.process(internal_data, title, content)


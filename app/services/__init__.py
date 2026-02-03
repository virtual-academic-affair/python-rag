"""Services for the application"""
from app.services.orchestration.langchain_service import LangChainClassifier
from app.services.domain.class_registration_service import ClassRegistrationService
from app.services.domain.administrative_service import AdministrativeService
from app.services.domain.graduation_service import GraduationService
from app.services.domain.academic_programme_service import AcademicProgrammeService
from app.services.domain.department_service import DepartmentService
from app.services.domain.other_service import OtherService

__all__ = [
    "LangChainClassifier",
    "ClassRegistrationService",
    "AdministrativeService",
    "GraduationService",
    "AcademicProgrammeService",
    "DepartmentService",
    "OtherService",
]


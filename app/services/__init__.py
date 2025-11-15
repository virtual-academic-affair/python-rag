"""Services for the application"""
from .langchain_service import LangChainClassifier
from .class_registration_service import ClassRegistrationService
from .administrative_service import AdministrativeService
from .graduation_service import GraduationService
from .academic_programme_service import AcademicProgrammeService
from .department_service import DepartmentService
from .other_service import OtherService

__all__ = [
    "LangChainClassifier",
    "ClassRegistrationService",
    "AdministrativeService",
    "GraduationService",
    "AcademicProgrammeService",
    "DepartmentService",
    "OtherService"
]


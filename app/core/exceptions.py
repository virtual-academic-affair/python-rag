"""
Custom exceptions for the application.
Unified exception hierarchy for classification and RAG features.
"""

from typing import Optional, Any


class AppException(Exception):
    """Base exception for the application."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        details: Optional[Any] = None
    ):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(self.message)



# ====================================
# NOT FOUND (404)
# ====================================

class NotFoundException(AppException):
    """Resource not found."""
    def __init__(self, resource: str, identifier: str = None):
        message = f"{resource} not found" + (f": {identifier}" if identifier else "")
        super().__init__(message, status_code=404)


# Aliases for backward compatibility
DocumentNotFoundException = NotFoundException
FileNotFoundException = NotFoundException
StoreNotFoundException = NotFoundException
FileNotFoundInStorageException = NotFoundException


# ====================================
# CONFLICT (409)
# ====================================

class ConflictException(AppException):
    """Resource conflict (duplicate, in-use, etc.)."""
    def __init__(self, message: str):
        super().__init__(message, status_code=409)


# Aliases
DuplicateDocumentException = ConflictException


class DefaultStoreException(ConflictException):
    """Cannot delete default store."""
    def __init__(self, store_name: str):
        super().__init__(f"Cannot delete default store: {store_name}. Set another default first.")


# ====================================
# FORBIDDEN (403)
# ====================================

class ForbiddenException(AppException):
    """Action forbidden (insufficient permissions, protected resource, etc.)."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=403, details=details)


# ====================================
# VALIDATION (400)
# ====================================

class ValidationException(AppException):
    """Validation failed."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=400, details=details)


class FileSizeException(ValidationException):
    """File size exceeds limit."""
    def __init__(self, size_mb: float, max_size_mb: int):
        super().__init__(f"File size {size_mb:.2f}MB exceeds maximum {max_size_mb}MB")


class FileTypeException(ValidationException):
    """File type not allowed."""
    def __init__(self, file_type: str, allowed_types: list[str]):
        super().__init__(f"File type '{file_type}' not allowed. Allowed: {', '.join(allowed_types)}")


# ====================================
# EXTERNAL SERVICE (500/502)
# ====================================

class StorageException(AppException):
    """Storage (R2) operation failed."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=500, details=details)


class FileUploadException(StorageException):
    """File upload failed."""
    pass


class FileDownloadException(StorageException):
    """File download failed."""
    pass


class GeminiException(AppException):
    """Gemini API operation failed."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=502, details=details)


class RabbitMQException(AppException):
    """RabbitMQ operation failed."""
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=500, details=details)


class ExternalServiceException(AppException):
    """External service (API) failed."""
    def __init__(self, message: str, status_code: int = 502, details: Optional[Any] = None):
        super().__init__(message, status_code=status_code, details=details)


class GrpcServerException(ExternalServiceException):
    """gRPC service call failed."""
    pass


# Legacy aliases for backward compatibility
DatabaseException = AppException

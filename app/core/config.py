"""
Unified Configuration Management using Pydantic Settings.
Merges settings from python-rag (classification) and rag-service (RAG).
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    """Unified application settings loaded from environment variables."""

    # ====================================
    # API Configuration
    # ====================================
    APP_NAME: str = "AI Service"
    APP_VERSION: str = "3.0.0"
    DEBUG: bool = False

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Uvicorn settings
    RELOAD: bool = True
    UVICORN_LOG_LEVEL: str = "info"

    # Application logging
    LOG_LEVEL: str = "INFO"

    # ====================================
    # Google Gemini Configuration
    # ====================================
    GOOGLE_API_KEY: str

    # Classification settings (from python-rag)
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_TEMPERATURE: float = 0.1
    LLM_THINKING_LEVEL: str = "none"
    GENAI_REQUEST_TIMEOUT: int = 60
    GENAI_MAX_OUTPUT_TOKENS_CLASSIFICATION: int = 100
    GENAI_MAX_OUTPUT_TOKENS_EXTRACTION: int = 1200

    # RAG settings (from rag-service)
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TEMPERATURE: float = 0.7
    GEMINI_MAX_OUTPUT_TOKENS: int = 2048
    GEMINI_TOP_P: float = 0.95
    GEMINI_TOP_K: int = 40
    GEMINI_TIMEOUT_SECONDS: int = 60

    # LlamaParse configuration (Sprint 1)
    LLAMA_CLOUD_API_KEY: Optional[str] = None
    LLAMA_PARSE_RESULT_TYPE: str = "markdown"
    LLAMA_PARSE_LANGUAGE: str = "vi"

    # Vectorless retrieval tuning (Sprint 4.2)
    VECTORLESS_TOP_K: int = 6
    VECTORLESS_MIN_SCORE: float = 1.0
    VECTORLESS_MAX_SCAN_DOCS: int = 3000
    VECTORLESS_CACHE_TTL_SECONDS: int = 30
    VECTORLESS_CACHE_MAX_KEYS: int = 200
    VECTORLESS_EXTRA_STOPWORDS: str = ""




    # ====================================
    # MongoDB Configuration
    # ====================================
    MONGODB_URL: str
    MONGODB_DB_NAME: str = "ai_service"
    MONGODB_MIN_POOL_SIZE: int = 10
    MONGODB_MAX_POOL_SIZE: int = 100
    MONGODB_DISABLED: bool = False

    # ====================================
    # r2/S3 Configuration
    # ====================================
    R2_ENDPOINT: str = "http://localhost:9000"
    R2_ACCESS_KEY: str = ""
    R2_SECRET_KEY: str = ""
    R2_BUCKET_NAME: str = "rag-files"
    R2_USE_SSL: bool = False
    R2_REGION: str = "us-east-1"
    R2_DISABLED: bool = False
    R2_BYPASS_ON_INIT_ERROR: bool = False
    R2_PUBLIC_DOMAIN: Optional[str] = None

    # ====================================
    # gRPC (shared workflows)
    # ====================================
    GRPC_ENABLED: bool = False
    GRPC_URL: str = "localhost:5000"
    GRPC_TIMEOUT_SECONDS: float = 3.0

    # ====================================
    # RabbitMQ Configuration
    # ====================================
    RABBITMQ_ENABLED: bool = True
    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"
    RABBITMQ_VHOST: str = "/"
    RABBITMQ_INGEST_QUEUE: str = "email_ingest_queue"

    # ====================================
    # File Upload Configuration
    # ====================================
    MAX_FILE_SIZE_MB: int = 20

    # ====================================
    # Rate Limiting
    # ====================================
    MAX_REQUESTS_PER_MINUTE: int = 60

    # ====================================
    # CORS Configuration
    # ====================================
    CORS_ORIGINS: list[str] = ["*"]

    # ====================================
    # Pydantic Config
    # ====================================
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


# Singleton instance
settings = Settings()

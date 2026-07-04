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
    APP_VERSION: str = "5.5.0"
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

    # RAG settings (from rag-service)
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TEMPERATURE: float = 0.7
    GEMINI_TOP_P: float = 0.95
    GEMINI_TOP_K: int = 40
    GEMINI_TIMEOUT_SECONDS: int = 60
    AGENT_MAX_TURNS: int = 7

    # LlamaParse configuration (Sprint 1)
    LLAMA_CLOUD_API_KEY: Optional[str] = None
    LLAMA_PARSE_RESULT_TYPE: str = "markdown"
    LLAMA_PARSE_LANGUAGE: str = "vi"
    LLAMA_PARSE_USE_PREMIUM: bool = False

    # Vectorless navigator (LLM catalog navigation for file retrieval).
    RETRIEVAL_NAVIGATOR_MAX_CATALOG: int = 500
    # None -> falls back to GEMINI_MODEL.
    RETRIEVAL_NAVIGATOR_MODEL: Optional[str] = None
    
    # PageIndex configuration
    PAGEINDEX_WORKSPACE: str = "storage/pageindex_workspace"
    PAGEINDEX_MODEL: str = "gemma-4-31b-it" 
    PAGEINDEX_RETRIEVE_MODEL: str = "gemma-4-31b-it" 
    PAGEINDEX_TOC_CHECK_PAGE_NUM: int = 20
    PAGEINDEX_MAX_PAGE_NUM_EACH_NODE: int = 10
    PAGEINDEX_MAX_TOKEN_NUM_EACH_NODE: int = 20000
    PAGEINDEX_SUMMARY_TOKEN_THRESHOLD: int = 200
    PAGEINDEX_IF_ADD_NODE_ID: str = "yes"
    PAGEINDEX_IF_ADD_NODE_SUMMARY: str = "yes"
    PAGEINDEX_IF_ADD_DOC_DESCRIPTION: str = "no"
    PAGEINDEX_IF_ADD_NODE_TEXT: str = "no"

    # ====================================
    # FAQ Configuration
    # ====================================
    # FAQ_MATCHER_MODEL: None -> falls back to GEMINI_MODEL.
    FAQ_MATCHER_MAX_CATALOG: int = 200
    FAQ_MATCHER_MODEL: Optional[str] = None
    # None -> falls back to GEMINI_MODEL.
    CORPUS_TOPIC_MODEL: Optional[str] = None
    FAQ_SYNTHESIS_CLUSTERING_THRESHOLD: float = 0.85
    FAQ_SYNTHESIS_ENABLED: bool = False
    FAQ_SYNTHESIS_INTERVAL_DAYS: int = 7
    FAQ_SYNTHESIS_MIN_CLUSTER_SIZE: int = 10
    FAQ_SYNTHESIS_LOOKBACK_DAYS: int = 30
    FAQ_LOG_RETENTION_DAYS: int = 90
    FAQ_LOG_MIN_QUESTION_LENGTH: int = 15


    # ====================================
    # MongoDB Configuration
    # ====================================
    MONGODB_URL: str
    MONGODB_DB_NAME: str = "ai_service"
    MONGODB_MIN_POOL_SIZE: int = 1
    MONGODB_MAX_POOL_SIZE: int = 20

    # ====================================
    # r2/S3 Configuration
    # ====================================
    R2_ENDPOINT: str = "http://localhost:9000"
    R2_ACCESS_KEY: str = ""
    R2_SECRET_KEY: str = ""
    R2_BUCKET_NAME: str = "rag-files"
    R2_USE_SSL: bool = False
    R2_REGION: str = "us-east-1"
    R2_PUBLIC_DOMAIN: Optional[str] = None

    # ====================================
    # gRPC (shared workflows)
    # ====================================
    GRPC_ENABLED: bool = False
    GRPC_URL: str = "localhost:5000"
    GRPC_TIMEOUT_SECONDS: float = 3.0

    # ====================================
    # JWT Configuration
    # ====================================
    JWT_SECRET: str = "CHANGE_ME_SUPER_SECRET"
    JWT_TOKEN_AUDIENCE: str = "vaa"
    JWT_TOKEN_ISSUER: str = "vaa-api"

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
    RABBITMQ_EMAIL_DLX: str = "email_ingest_dlx"
    RABBITMQ_EMAIL_DLQ: str = "email_ingest_dlq"
    RABBITMQ_EMAIL_MAX_RETRIES: int = 1

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
    # Redis Configuration
    # ====================================
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = True
    REDIS_TIMEOUT: int = 5

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

"""Application settings and configuration"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings"""
    
    # API Keys
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    
    # LangChain/LLM settings
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-2.5-flash-lite")
    LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    
    # Server settings
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Uvicorn settings
    RELOAD: bool = os.getenv("RELOAD", "true").lower() in ("true", "1", "yes")
    UVICORN_LOG_LEVEL: str = os.getenv("UVICORN_LOG_LEVEL", "info").lower()
    
    # Application logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # JWT settings
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

    # RabbitMQ settings
    RABBITMQ_HOST: str = os.getenv("RABBITMQ_HOST", "localhost")
    RABBITMQ_PORT: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER: str = os.getenv("RABBITMQ_USER", "guest")
    RABBITMQ_PASSWORD: str = os.getenv("RABBITMQ_PASSWORD", "guest")
    RABBITMQ_VHOST: str = os.getenv("RABBITMQ_VHOST", "/")
    RABBITMQ_INGEST_QUEUE: str = os.getenv("RABBITMQ_INGEST_QUEUE", "queue")

    # gRPC settings (shared for multiple workflows)
    GRPC_ENABLED: bool = os.getenv("GRPC_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    GRPC_URL: str = os.getenv("GRPC_URL", "103.20.96.59:5000")
    GRPC_TIMEOUT_SECONDS: float = float(os.getenv("GRPC_TIMEOUT_SECONDS", "3"))

    @classmethod
    def validate(cls):
        """Validate required settings"""
        if not cls.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY environment variable is required")
        if not cls.JWT_SECRET_KEY:
            raise ValueError("JWT_SECRET_KEY environment variable is required")


settings = Settings()


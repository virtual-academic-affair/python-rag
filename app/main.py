"""Main FastAPI application"""
import os
import logging
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from app.api.routes import router
from app.services.orchestration.email_workflow_orchestrator import EmailWorkflowOrchestrator
from app.models.schemas import ProcessResponse

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global classifier instance
classifier = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    global classifier

    # Startup
    from config.settings import settings
    from app.services.messaging.rabbitmq_service import get_rabbitmq_service

    if not settings.GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY environment variable is required")

    # Initialize RabbitMQ service
    try:
        rabbitmq_service = get_rabbitmq_service()
        logger.info("RabbitMQ service initialized")
    except Exception as e:
        logger.warning(f"RabbitMQ initialization warning: {str(e)}")
        rabbitmq_service = None

    classifier = EmailWorkflowOrchestrator(
        api_key=settings.GOOGLE_API_KEY,
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE
    )
    logger.info(f"LangChain classifier initialized with model: {settings.LLM_MODEL}")

    consumer_thread = None
    if rabbitmq_service is not None:
        try:
            from app.services.messaging.email_ingest_consumer import start_email_ingest_consumer

            loop = asyncio.get_running_loop()
            consumer_thread = start_email_ingest_consumer(classifier, loop=loop)
            logger.info("Email ingest consumer started")
        except Exception as e:
            logger.warning(f"Email ingest consumer not started: {str(e)}")

    yield

    # Shutdown
    try:
        if rabbitmq_service is not None:
            rabbitmq_service.close()
    except:
        pass
    logger.info("Application shutting down")


# Create FastAPI app
app = FastAPI(
    title="Student Classification Service",
    description="A FastAPI service that classifies student and class data using LangChain with Gemini",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle validation errors."""
    logger.error(f"Validation error: {str(exc)}")
    return ProcessResponse(
        success=False,
        error=f"Validation error: {str(exc)}"
    )


if __name__ == "__main__":
    import uvicorn
    from config.settings import settings
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.UVICORN_LOG_LEVEL
    )


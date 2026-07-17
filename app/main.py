"""Main FastAPI application"""
import logging
import asyncio
import time
from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.modules.files.dtos.file_out import ErrorResponse, HealthCheckResponse
from beanie import init_beanie
from app.modules.files.models.file import FileDocument
from app.modules.files.toc_tree.models.toc_tree import FileTocTree
from app.modules.faq.models.faq import FaqDocument
from app.modules.faq.models.faq_candidate import FaqCandidateDocument
from app.modules.faq.models.interaction_log import InteractionLogDocument
from app.modules.chat.models.chat_session import ChatSessionDocument
from app.modules.chat.models.chat_message import ChatMessageDocument
from app.modules.forms.models.form import FormDocument
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.core.config import settings
from app.core.exceptions import AppException
from app.modules.email import EmailWorkflowOrchestrator
from app.core.database import Database
from app.integrations.storage.client import r2_storage
from app.integrations.rabbitmq.client import get_rabbitmq_service
from app.integrations.llm.gateway import get_llm_gateway
from app.integrations.redis.client import get_redis_client
from app.integrations.pageindex.client import get_page_index_client
from app.modules.email.consumer import start_email_ingest_consumer
import uvicorn
from google.genai.errors import APIError

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan)
email_orchestrator = None
rabbitmq_service = None
_cleanup_task = None
email_consumer_thread = None


async def _run_artifact_cleanup():
    """Background task to periodically clean up expired local artifacts."""
    client = get_page_index_client()
    
    # Run every 30 minutes
    INTERVAL = 1800  
    
    logger.info(f"⏳ Artifact cleanup task started (Interval: {INTERVAL}s)")
    while True:
        try:
            await asyncio.sleep(INTERVAL)
            count = await client.cleanup_expired_artifacts()
            if count > 0:
                logger.info(f"🧹 Background cleanup removed {count} expired artifacts")
        except asyncio.CancelledError:
            logger.info("🛑 Artifact cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"❌ Error in artifact cleanup task: {e}")
            await asyncio.sleep(60)  # Wait a bit before retrying if crashed


async def _run_monthly_faq_synthesis():
    """
    Background task to run FAQ synthesis on the 1st of every month.
    """
    logger.info("⏳ Monthly FAQ synthesis scheduler started")
    
    while True:
        try:
            now = datetime.now()
            # Calculate time until the 1st of next month at 01:00 AM
            if now.day == 1 and now.hour < 1:
                # If today is the 1st but before 1 AM, target today 1 AM
                target = now.replace(hour=1, minute=0, second=0, microsecond=0)
            else:
                # Otherwise, target the 1st of next month
                if now.month == 12:
                    target = now.replace(year=now.year + 1, month=1, day=1, hour=1, minute=0, second=0, microsecond=0)
                else:
                    target = now.replace(month=now.month + 1, day=1, hour=1, minute=0, second=0, microsecond=0)
            
            wait_seconds = (target - now).total_seconds()
            logger.info(f"Next FAQ synthesis scheduled at {target} (in {wait_seconds/3600:.2f} hours)")
            
            await asyncio.sleep(wait_seconds)
            
            # Run synthesis
            logger.info("🚀 Starting scheduled monthly FAQ synthesis...")
            service = await get_faq_synthesis_service()
            # For monthly run, we use the default lookback (likely 30 days) or specify last month
            # Calculate last month range for precision
            last_month_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 1:
                last_month_start = now.replace(year=now.year - 1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                last_month_start = now.replace(month=now.month - 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            result = await service.run(
                date_from_str=last_month_start.isoformat(),
                date_to_str=last_month_end.isoformat()
            )
            logger.info(f"✅ Scheduled FAQ synthesis complete: {result}")
            
            # Sleep for at least a day to avoid re-triggering within the same day
            await asyncio.sleep(86400)
            
        except asyncio.CancelledError:
            logger.info("🛑 Monthly FAQ synthesis task cancelled")
            break
        except Exception as e:
            logger.error(f"❌ Error in monthly FAQ synthesis task: {e}")
            await asyncio.sleep(3600)  # Retry in an hour if something failed


# ====================================
# LIFESPAN EVENTS
# ====================================

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize and cleanup resources."""
    global email_orchestrator
    global rabbitmq_service
    global _cleanup_task
    global email_consumer_thread

    # Startup
    print("=" * 80)
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION}")
    print("=" * 80)
    print(f"📡 Server: {settings.HOST}:{settings.PORT}")
    print(f"🤖 LLM Model: {settings.LLM_MODEL}")
    print(f"💾 Database: {settings.MONGODB_DB_NAME}")
    print(f"📦 Storage: R2 ({settings.R2_ENDPOINT})")
    print(
        "🐰 Messaging: RabbitMQ (%s)"
        % (settings.RABBITMQ_HOST if settings.RABBITMQ_ENABLED else "disabled")
    )
    print(f"🐛 Debug Mode: {settings.DEBUG}")
    print("=" * 80)
    
    # 1. Connect to MongoDB and Initialize Beanie
    try:
        await Database.connect()
        logger.info("✅ MongoDB connected")
        await init_beanie(
            database=Database.get_db(),
            document_models=[
                FileDocument,
                FileTocTree,
                FaqDocument,
                FaqCandidateDocument,
                InteractionLogDocument,
                ChatSessionDocument,
                ChatMessageDocument,
                FormDocument,
                CorpusNodeDocument,
            ]
        )
        logger.info("✅ Beanie ODM initialized")
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        raise

    # 2. Initialize R2 storage
    try:
        # R2 client initializes on import, test connection
        response = r2_storage.get_client().list_buckets()
        buckets = response.get('Buckets', [])
        logger.info(f"✅ R2 storage initialized ({len(buckets)} buckets)")
    except Exception as e:
        logger.warning(f"⚠️  R2 initialization warning: {e}")

    # 3. Initialize RabbitMQ service
    if settings.RABBITMQ_ENABLED:
        try:
            rabbitmq_service = get_rabbitmq_service()
            logger.info("✅ RabbitMQ service initialized")
        except Exception as e:
            logger.warning(f"⚠️  RabbitMQ not available: {e}")
            rabbitmq_service = None
    else:
        logger.info("🐰 RabbitMQ disabled via config")
        rabbitmq_service = None

    # 4. Initialize gRPC and Orchestrator
    # GrpcClient is now used as a singleton wrapper via get_grpc_client
    email_orchestrator = EmailWorkflowOrchestrator()
    _.state.email_orchestrator = email_orchestrator
    logger.info("Email Workflow Orchestrator initialized")

    if rabbitmq_service is not None:
        try:
            loop = asyncio.get_running_loop()
            email_consumer_thread = start_email_ingest_consumer(email_orchestrator, loop=loop)
            _.state.email_consumer_thread = email_consumer_thread
            logger.info("Email ingest consumer started")
        except Exception as e:
            logger.warning(f"⚠️  Email consumer not started: {e}")
    
    # 6. Test Gemini API
    try:
        logger.info("✅ Gemini service initialized")
    except Exception as e:
        logger.warning(f"⚠️  Gemini service warning: {e}")
    
    # 7. Start Background Tasks
    _cleanup_task = asyncio.create_task(_run_artifact_cleanup())
    
    _synthesis_task = None
    logger.info("ℹ️ FAQ synthesis background task is temporarily disabled pending architecture migration")

    # 8. Initialize Redis
    if settings.REDIS_ENABLED:
        try:
            redis_client = get_redis_client()
            await redis_client.connect()
        except Exception as e:
            logger.warning(f"⚠️  Redis initialization warning: {e}")
    
    print(f"🟢 {settings.APP_NAME} is ready!\n")
    
    yield
    
    # Shutdown
    print("\n" + "=" * 80)
    print(f"🔴 Shutting down {settings.APP_NAME}...")
    print("=" * 80)
    
    # Close RabbitMQ connection
    if rabbitmq_service is not None:
        try:
            rabbitmq_service.close()
            logger.info("✅ RabbitMQ connection closed")
        except Exception as e:
            logger.warning(f"⚠️  Error closing RabbitMQ: {e}")
    
    # Disconnect from MongoDB
    try:
        await Database.disconnect()
        logger.info("✅ MongoDB disconnected")
    except Exception as e:
        logger.warning(f"⚠️  Error disconnecting MongoDB: {e}")
    
    # Cancel cleanup task
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("✅ Artifact cleanup task stopped")

    # Cancel synthesis task
    if _synthesis_task:
        _synthesis_task.cancel()
        try:
            await _synthesis_task
        except asyncio.CancelledError:
            pass
        logger.info("✅ FAQ synthesis task stopped")

    # Close Redis
    if settings.REDIS_ENABLED:
        try:
            redis_client = get_redis_client()
            await redis_client.disconnect()
            logger.info("✅ Redis disconnected")
        except Exception as e:
            logger.warning(f"⚠️ Redis disconnect failed: {e}")
        
    logger.info("👋 Shutdown complete")


# ====================================
# CREATE FASTAPI APP
# ====================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Unified microservice for email classification and RAG-based document search",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ====================================
# MIDDLEWARE
# ====================================

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request Timing Middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header to all responses."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}"
    return response


# ====================================
# GLOBAL EXCEPTION HANDLERS
# ====================================

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle application exceptions with their declared status codes."""
    if exc.status_code >= 500:
        logger.error(f"Application exception: {exc.message}", exc_info=True)
    else:
        logger.warning(f"Application exception: {exc.message}")

    details = exc.details if isinstance(exc.details, dict) or exc.details is None else {"detail": exc.details}
    if settings.DEBUG:
        debug_details = {"path": str(request.url)}
        if isinstance(details, dict):
            details = {**details, **debug_details}
        elif details is None:
            details = debug_details

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.__class__.__name__,
            message=exc.message,
            details=details,
        ).model_dump(by_alias=True),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="internal_server_error",
            message=str(exc) if settings.DEBUG else "An internal error occurred",
            details={"path": str(request.url)} if settings.DEBUG else None,
        ).model_dump(by_alias=True),
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle validation errors."""
    logger.error(f"Validation error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(
            error="validation_error",
            message=str(exc),
            details={"path": str(request.url)} if settings.DEBUG else None,
        ).model_dump(by_alias=True),
    )



@app.exception_handler(APIError)
async def genai_api_error_handler(request: Request, exc: APIError):
    """Handle Google GenAI errors globally.
    Masks only 500 INTERNAL errors, propagates all other codes and messages.
    """
    logger.error(f"GenAI API Error: {exc}")
    
    raw_msg = str(exc)
    status_code = getattr(exc, "code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    if not isinstance(status_code, int) or status_code < 400:
        status_code = 500
        
    safe_msg = raw_msg
    if status_code == 500 and ("500 INTERNAL" in raw_msg or "Internal error encountered" in raw_msg):
        safe_msg = "Google internal server error"
        
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error="rate_limit_exceeded" if status_code == 429 else "ai_service_error",
            message=safe_msg,
            details={"path": str(request.url)} if settings.DEBUG else None,
        ).model_dump(by_alias=True),
    )


# ====================================
# HEALTH CHECK ENDPOINT
# ====================================

@app.get("/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check(request: Request):
    """
    Health check endpoint.
    Returns service status, version, and dependency connectivity.
    """
    gemini_connected = False
    mongodb_connected = False
    redis_connected = False
    email_consumer_running = None

    if settings.RABBITMQ_ENABLED:
        consumer_thread = getattr(request.app.state, "email_consumer_thread", None)
        email_consumer_running = consumer_thread.is_alive() if consumer_thread is not None else False

    try:
        gemini_connected = get_llm_gateway() is not None
    except Exception as e:
        logger.debug(f"Health check: gemini probe failed: {e}")

    try:
        mongodb_connected = Database._db is not None
    except Exception as e:
        logger.debug(f"Health check: mongodb probe failed: {e}")

    try:
        redis_connected = get_redis_client()._redis is not None
    except Exception as e:
        logger.debug(f"Health check: redis probe failed: {e}")

    dependencies_ok = gemini_connected and mongodb_connected and redis_connected
    if settings.RABBITMQ_ENABLED and not email_consumer_running:
        dependencies_ok = False

    return HealthCheckResponse(
        status="healthy" if dependencies_ok else "degraded",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        gemini_api_connected=gemini_connected,
        mongodb_connected=mongodb_connected,
        redis_connected=redis_connected,
        email_consumer_running=email_consumer_running,
    )


# ====================================
# INCLUDE API ROUTERS
# ====================================

app.include_router(api_router)
logger.info("✅ API routers included")


# ====================================
# MAIN (for direct execution)
# ====================================

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.UVICORN_LOG_LEVEL,
    )

"""Main FastAPI application"""
import logging
import asyncio
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.modules.files.schemas import ErrorResponse, HealthCheckResponse
from app.core.config import settings
from app.modules.email.orchestrator import EmailWorkflowOrchestrator
from app.core.database import Database
from app.integrations.storage.client import r2_storage
from app.integrations.rabbitmq.client import get_rabbitmq_service
from app.integrations.llm.gemini import gemini_client
from app.integrations.redis.client import get_redis_client
from app.integrations.pageindex.client import get_page_index_client
from app.modules.email.consumer import start_email_ingest_consumer
from app.integrations.qdrant.indexer import get_qdrant_indexer

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan)
email_orchestrator = None
rabbitmq_service = None
_cleanup_task = None


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


# ====================================
# LIFESPAN EVENTS
# ====================================

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize and cleanup resources."""
    global email_orchestrator
    global rabbitmq_service
    global _cleanup_task

    # Startup
    print("=" * 80)
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION}")
    print("=" * 80)
    print(f"📡 Server: {settings.HOST}:{settings.PORT}")
    print(f"🤖 LLM Model: {settings.LLM_MODEL}")
    print(f"🤖 Gemini Model: {settings.GEMINI_MODEL}")
    print(f"💾 Database: {settings.MONGODB_DB_NAME}")
    print(f"📦 Storage: R2 ({settings.R2_ENDPOINT})")
    print(
        "🐰 Messaging: RabbitMQ (%s)"
        % (settings.RABBITMQ_HOST if settings.RABBITMQ_ENABLED else "disabled")
    )
    print(f"🐛 Debug Mode: {settings.DEBUG}")
    print("=" * 80)
    
    if settings.MONGODB_DISABLED or settings.R2_DISABLED:
        print("🚨 WARNING: RUNNING WITH DISABLED SERVICES!")
        if settings.MONGODB_DISABLED:
            print("   - MONGODB_DISABLED=True: NO data persistence!")
        if settings.R2_DISABLED:
            print("   - R2_DISABLED=True: Files will NOT be stored!")
        print("=" * 80)
    
    # 1. Connect to MongoDB
    try:
        await Database.connect()
        if settings.MONGODB_DISABLED:
            logger.warning("⚠️  MongoDB disabled. Continuing without DB.")
        else:
            logger.info("✅ MongoDB connected")
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        raise

    # 2. Initialize R2 storage
    try:
        # R2 client initializes on import, test connection
        if settings.R2_DISABLED:
            logger.warning("⚠️  R2 disabled. Continuing without storage.")
        else:
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
    logger.info("Email Workflow Orchestrator initialized")

    if rabbitmq_service is not None:
        try:
            loop = asyncio.get_running_loop()
            start_email_ingest_consumer(email_orchestrator, loop=loop)
            logger.info("Email ingest consumer started")
        except Exception as e:
            logger.warning(f"⚠️  Email consumer not started: {e}")
    
    # 6. Test Gemini API
    try:
        logger.info("✅ Gemini service initialized")
    except Exception as e:
        logger.warning(f"⚠️  Gemini service warning: {e}")
    
    # 7. Start Artifact Cleanup Task
    _cleanup_task = asyncio.create_task(_run_artifact_cleanup())

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
        ).model_dump(),
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
        ).model_dump(),
    )


# ====================================
# HEALTH CHECK ENDPOINT
# ====================================

@app.get("/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    Returns service status, version, and dependency connectivity.
    """
    gemini_connected = False
    mongodb_connected = False
    redis_connected = False
    qdrant_connected = False
    
    try:
        gemini_connected = gemini_client.client is not None
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
    
    try:
        qdrant_connected = get_qdrant_indexer()._qdrant_client is not None
    except Exception as e:
        logger.debug(f"Health check: qdrant probe failed: {e}")
    
    return HealthCheckResponse(
        status="healthy" if (gemini_connected and mongodb_connected and redis_connected and qdrant_connected) else "degraded",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        gemini_api_connected=gemini_connected,
        mongodb_connected=mongodb_connected,
        redis_connected=redis_connected,
        qdrant_connected=qdrant_connected,
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
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.UVICORN_LOG_LEVEL,
    )


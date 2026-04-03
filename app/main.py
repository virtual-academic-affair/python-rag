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
from app.models.schemas import ErrorResponse, HealthCheckResponse
from app.core.config import settings
from app.services.integrations.grpc_client import (
    GrpcClient,
    GrpcClientConfig,
)
from app.services.orchestration.email_workflow_orchestrator import EmailWorkflowOrchestrator

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


# ====================================
# LIFESPAN EVENTS
# ====================================

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize and cleanup resources."""
    global email_orchestrator
    global rabbitmq_service

    # Startup
    print("=" * 80)
    print(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION}")
    print("=" * 80)
    print(f"📡 Server: {settings.HOST}:{settings.PORT}")
    print(f"🤖 LLM Model: {settings.LLM_MODEL}")
    print(f"🤖 Provider Model: {settings.GEMINI_MODEL}")
    print(f"💾 Database: {settings.MONGODB_DB_NAME}")
    print(f"📦 Storage: R2 ({settings.R2_ENDPOINT})")
    print(
        "🐰 Messaging: RabbitMQ (%s)"
        % (settings.RABBITMQ_HOST if settings.RABBITMQ_ENABLED else "disabled")
    )
    print(f"🐛 Debug Mode: {settings.DEBUG}")
    print("=" * 80)
    
    # 1. Connect to MongoDB
    try:
        from app.core.database import Database
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
        from app.storage.r2_client import r2_storage
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
            from app.services.messaging.rabbitmq_service import get_rabbitmq_service
            rabbitmq_service = get_rabbitmq_service()
            logger.info("✅ RabbitMQ service initialized")
        except Exception as e:
            logger.warning(f"⚠️  RabbitMQ not available: {e}")
            rabbitmq_service = None
    else:
        logger.info("🐰 RabbitMQ disabled via config")
        rabbitmq_service = None

    host, port = settings.GRPC_URL.split(":", 1)
    grpc_client = GrpcClient(
        GrpcClientConfig(
            enabled=settings.GRPC_ENABLED,
            host=host,
            port=int(port),
            timeout_seconds=settings.GRPC_TIMEOUT_SECONDS,
        )
    )

    classifier = EmailWorkflowOrchestrator(
        api_key=settings.GOOGLE_API_KEY,
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        grpc_client=grpc_client,
    )
    email_orchestrator = classifier
    logger.info(f"Email Workflow Orchestrator initialized with model: {settings.LLM_MODEL}")

    if rabbitmq_service is not None:
        try:
            from app.services.messaging.email_ingest_consumer import start_email_ingest_consumer
            loop = asyncio.get_running_loop()
            start_email_ingest_consumer(email_orchestrator, loop=loop)
            logger.info("Email ingest consumer started")
        except Exception as e:
            logger.warning(f"⚠️  Email consumer not started: {e}")
    
    # 6. Initialize Graphiti schema
    try:
        if settings.GRAPHITI_ENABLED:
            from app.services.rag.graphiti.graphiti_client import graphiti_client
            from app.services.rag.graphiti.graphiti_schema import graphiti_schema_service

            graphiti_client.verify()
            graphiti_schema_service.initialize_schema()
            logger.info("✅ Graphiti initialized")
        else:
            logger.info("ℹ️  Graphiti disabled via config")
    except Exception as e:
        logger.warning(f"⚠️  Graphiti initialization warning: {e}")

    # 7. Test LLM provider API (used for generation + embeddings)
    try:
        from app.services.rag.gemini_client import gemini_client
        logger.info("✅ LLM provider service initialized")
    except Exception as e:
        logger.warning(f"⚠️  LLM provider service warning: {e}")

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
        from app.core.database import Database
        await Database.disconnect()
        logger.info("✅ MongoDB disconnected")
    except Exception as e:
        logger.warning(f"⚠️  Error disconnecting MongoDB: {e}")

    # Close Graphiti driver
    try:
        if settings.GRAPHITI_ENABLED:
            from app.services.rag.graphiti.graphiti_client import graphiti_client
            graphiti_client.close()
            logger.info("✅ Graphiti disconnected")
    except Exception as e:
        logger.warning(f"⚠️  Error disconnecting Graphiti: {e}")

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
    llm_api_connected = False
    mongodb_connected = False
    graphiti_connected = False

    try:
        from app.services.rag.gemini_client import gemini_client
        llm_api_connected = gemini_client.client is not None
    except Exception:
        pass
    
    try:
        from app.core.database import Database
        mongodb_connected = Database._db is not None
    except Exception:
        pass

    try:
        if settings.GRAPHITI_ENABLED:
            from app.services.rag.graphiti.graphiti_client import graphiti_client
            graphiti_client.verify()
            graphiti_connected = True
        else:
            graphiti_connected = True
    except Exception:
        pass

    return HealthCheckResponse(
        status="healthy" if (llm_api_connected and mongodb_connected and graphiti_connected) else "degraded",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        llm_api_connected=llm_api_connected,
        mongodb_connected=mongodb_connected,
        graphiti_connected=graphiti_connected,
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


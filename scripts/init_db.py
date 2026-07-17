"""
Database & Storage Initialization Script for AI Service (python-rag).

Tác vụ                | Câu lệnh
----------------------|----------------------------------------------------------------------
Sao lưu dữ liệu      | python scripts/snapshot.py export scripts/uploads_result/rag_backup.json
Khôi phục dữ liệu    | python scripts/init_db.py --restore scripts/uploads_result/rag_backup.json
Khởi tạo gốc (AI)    | python scripts/init_db.py --skip-confirm
"""

import asyncio
import logging
import json
import os
import sys
import httpx
from pathlib import Path
import time
from datetime import datetime

from beanie import init_beanie
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, TEXT

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

from scripts.snapshot import SnapshotManager
from scripts.seed_faqs import main as seed_faqs_main
from app.core.config import settings
from app.core.database import Database
from app.integrations.storage.client import r2_storage
from app.modules.corpus.models.corpus_node import CorpusNodeDocument
from app.modules.corpus.repositories.corpus_node_repository import CorpusNodeRepository
from scripts.seed_corpus import seed_corpus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ====================================
# Configuration
# ====================================
API_BASE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8000")
API_URL = f"{API_BASE_URL}/api"
SCRIPT_DIR = Path(__file__).parent
UPLOADS_DIR = SCRIPT_DIR / "uploads"
INIT_DATA_FILE = SCRIPT_DIR / "init_data.json"

# Admin JWT token — replace with a valid admin token when running
AUTH_TOKEN = os.getenv(
    "INIT_AUTH_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOjEzLCJlbWFpbCI6Im5kbWFuaDIyQGNsYy5maXR1cy5lZHUudm4iLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3NzcyMjQyNjMsImV4cCI6MzYwMDE3NzcyMjQyNjMsImF1ZCI6InZhYSIsImlzcyI6InZhYS1hcGkifQ"
    ".aRAaOBJvHS9g9SmpZEZWCaculOs9vHLkSXF7PVhGE9o"
)
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


# ====================================
# Phase 1: Clear existing data
# ====================================

async def drop_mongodb_database():
    """Drop all MongoDB collections."""
    logger.info("Dropping MongoDB database...")

    mongodb_url = os.getenv("MONGODB_URL")
    db_name = os.getenv("MONGODB_DB_NAME", "ai_service")

    if not mongodb_url:
        raise ValueError("MONGODB_URL not set in .env")

    client = AsyncIOMotorClient(mongodb_url)
    db = client[db_name]

    collections = await db.list_collection_names()

    if not collections:
        logger.info("  No collections found. Database is already empty.")
    else:
        for col in collections:
            await db[col].drop()
            logger.info(f"  ✓ Dropped collection: {col}")

    client.close()
    logger.info("✅ MongoDB database dropped")


async def clear_r2_bucket():
    """Delete all files from R2 bucket."""
    logger.info("Clearing R2 bucket...")
    
    try:

        files = await r2_storage.list_files()
        if not files:
            logger.info("  Bucket is already empty")
        else:
            delete_count = 0
            for f in files:
                # In modular storage, list_files returns a list of dicts with 'object_name'
                await r2_storage.delete_file(f["object_name"])
                delete_count += 1
            
            logger.info(f"  ✓ Deleted {delete_count} files from bucket")

    except Exception as e:
        logger.warning(f"  R2 error (continuing): {e}")

    logger.info("✅ R2 bucket cleared")


async def clear_pageindex_workspace():
    """Delete all .md and .json files in PageIndex workspace."""
    logger.info("Clearing PageIndex workspace...")

    workspace_dir = Path(settings.PAGEINDEX_WORKSPACE)
    if not workspace_dir.exists():
        logger.info("  Workspace directory does not exist, skipping.")
        return

    try:
        delete_count = 0
        for ext in ["*.md", "*.json"]:
            for f in workspace_dir.glob(ext):
                f.unlink()
                delete_count += 1
        logger.info(f"  ✓ Deleted {delete_count} files from workspace")
    except Exception as e:
        logger.warning(f"  Workspace clearing error (continuing): {e}")

    logger.info("✅ PageIndex workspace cleared")

# ====================================
# Phase 2: Initialize
# ====================================

async def _seed_corpus_nodes():
    """Seed the corpus topic tree into MongoDB (idempotent, does not overwrite custom links)."""
    logger.info("Seeding corpus nodes...")

    await init_beanie(
        database=Database.get_db(),
        document_models=[CorpusNodeDocument]
    )

    repo = CorpusNodeRepository()
    created = await seed_corpus(repo)
    logger.info(f"✓ Seeded corpus: {created} new topic nodes created")


async def create_database_indexes(skip_seeding: bool = False):
    """Create MongoDB indexes."""
    logger.info("Creating database indexes...")

    await Database.connect()
    db = Database.get_db()

    # Files collection indexes
    await db[Database.FILES].create_index([("status", ASCENDING)])
    await db[Database.FILES].create_index([("created_at", DESCENDING)])
    await db[Database.FILES].create_index(
        [("deleted_at", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)],
        name="idx_files_deleted_status_created",
    )

    # FAQ collection indexes — names must match Settings.indexes in faq.py (Beanie is source of truth)
    await db[Database.FAQS].create_index(
        [("question_unaccented", TEXT), ("answer_unaccented", TEXT)],
        name="idx_faqs_text"
    )
    await db[Database.FAQS].create_index(
        [("question_unaccented", ASCENDING)],
        unique=True,
        partialFilterExpression={"deleted_at": None},
        name="idx_faqs_question_unique"
    )
    await db[Database.FAQS].create_index(
        [("deleted_at", ASCENDING), ("created_at", DESCENDING)],
        name="idx_faqs_deleted_created",
    )
    # Corpus Nodes collection indexes
    await db["corpus_nodes"].create_index(
        [("node_key", ASCENDING)],
        unique=True,
        name="idx_corpus_node_key"
    )
    await db["corpus_nodes"].create_index([("parent_key", ASCENDING)], name="parent_key_1")
    await db["corpus_nodes"].create_index([("direct_file_ids", ASCENDING)], name="direct_file_ids_1")
    await db["corpus_nodes"].create_index([("direct_faq_ids", ASCENDING)], name="direct_faq_ids_1")
    await db["corpus_nodes"].create_index([("subtree_file_ids", ASCENDING)], name="subtree_file_ids_1")
    await db["corpus_nodes"].create_index([("subtree_faq_ids", ASCENDING)], name="subtree_faq_ids_1")

    if not skip_seeding:
        await _seed_corpus_nodes()

    await Database.disconnect()


async def upload_files(files_config: list) -> list[str]:
    """Upload files via API (requires admin auth). Returns list of file IDs."""
    logger.info("Uploading files...")

    success_count = 0
    fail_count = 0
    uploaded_ids = []

    async with httpx.AsyncClient(timeout=300) as client:
        for file_config in files_config:
            filename = file_config["filename"]
            display_name = file_config["displayName"]
            metadata = file_config.get("metadata", {})
            lecturer_only = file_config.get("lecturerOnly", False)

            file_path = UPLOADS_DIR / filename

            if not file_path.exists():
                logger.warning(f"  ⚠ File not found: {file_path}")
                fail_count += 1
                continue

            try:
                with open(file_path, "rb") as f:
                    files = {"file": (filename, f, "application/octet-stream")}
                    data = {
                        "displayName": display_name,
                        "customMetadata": json.dumps(metadata),
                        "lecturerOnly": str(lecturer_only).lower(),
                    }

                    response = await client.post(
                        f"{API_URL}/files",
                        files=files,
                        data=data,
                        headers=AUTH_HEADERS
                    )

                if response.status_code == 201:
                    result = response.json()
                    file_id = result['fileId']
                    logger.info(f"  ✓ Uploaded: {display_name} (ID: {file_id})")
                    uploaded_ids.append(file_id)
                    success_count += 1
                else:
                    logger.warning(f"  ⚠ Failed to upload {filename}: {response.text}")
                    fail_count += 1

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"  ⚠ Error uploading {filename}: {e}")
                fail_count += 1

    logger.info(f"✅ File upload complete: {success_count} success, {fail_count} failed")
    return uploaded_ids


async def wait_for_ingestion(file_ids: list[str]):
    """Wait for all files to reach 'ready' or 'failed' status."""
    if not file_ids:
        return

    logger.info(f"Waiting for {len(file_ids)} files to complete ingestion...")
    
    pending_ids = set(file_ids)
    completed_ids = set()
    failed_ids = set()
    
    max_wait_minutes = 60
    start_time = time.time()
    
    async with httpx.AsyncClient(timeout=60) as client:
        while pending_ids:
            if (time.time() - start_time) > (max_wait_minutes * 60):
                logger.warning(f"  ⚠ Timeout waiting for ingestion after {max_wait_minutes} minutes")
                break
                
            for file_id in list(pending_ids):
                try:
                    response = await client.get(
                        f"{API_URL}/files/{file_id}",
                        headers=AUTH_HEADERS
                    )
                    if response.status_code == 200:
                        data = response.json()
                        status = data.get("status")
                        
                        if status == "ready":
                            logger.info(f"    ✓ File {file_id} is READY")
                            completed_ids.add(file_id)
                            pending_ids.remove(file_id)
                        elif status == "failed":
                            error_msg = data.get("errorMessage", "Unknown error")
                            logger.error(f"    ❌ File {file_id} FAILED: {error_msg}")
                            failed_ids.add(file_id)
                            pending_ids.remove(file_id)
                except Exception as e:
                    logger.warning(f"    ⚠ Error checking status for {file_id}: {e}")
            
            if pending_ids:
                logger.info(f"  ... still waiting for {len(pending_ids)} files ...")
                await asyncio.sleep(10)
    
    logger.info("-" * 50)
    logger.info(f"INGESTION STATUS: {len(completed_ids)} ready, {len(failed_ids)} failed, {len(pending_ids)} timed out")
    logger.info("-" * 50)

async def wait_for_service():
    """Wait for AI Service to be available."""
    logger.info("Checking AI Service availability...")

    max_retries = 10
    for i in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{API_BASE_URL}/health")
                if response.status_code == 200:
                    logger.info("  ✓ AI Service is running")
                    return True
        except Exception:
            pass

        if i < max_retries - 1:
            logger.info(f"  Waiting for service... ({i + 1}/{max_retries})")
            await asyncio.sleep(2)

    raise Exception(f"AI Service not available at {API_BASE_URL}")


# ====================================
# Main
# ====================================

async def main(skip_confirm: bool = False, restore_path: str = None):
    """Main initialization function."""
    print("=" * 70)
    print("AI SERVICE (python-rag) - FULL INITIALIZATION")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"API URL: {API_URL}")
    print(f"Uploads Directory: {UPLOADS_DIR}")
    print("=" * 70)

    if not skip_confirm:
        print("\n⚠️  WARNING: This will DELETE all existing data!")
        print("   - MongoDB database will be dropped")
        print("   - R2 files will be deleted")
        print()
        confirm = input("Continue? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            sys.exit(0)

    print()

    try:
        if not INIT_DATA_FILE.exists():
            raise FileNotFoundError(f"Init data file not found: {INIT_DATA_FILE}")

        with open(INIT_DATA_FILE, "r", encoding="utf-8") as f:
            init_data = json.load(f)

        logger.info(f"Loaded init data from {INIT_DATA_FILE}")

        # Phase 1: Clear everything
        print("\n" + "-" * 50)
        print("PHASE 1: CLEARING EXISTING DATA")
        print("-" * 50)

        await drop_mongodb_database()
        await clear_r2_bucket()
        await clear_pageindex_workspace()

        # Phase 2: Initialize
        print("\n" + "-" * 50)
        print("PHASE 2: INITIALIZING")
        print("-" * 50)

        await create_database_indexes(skip_seeding=bool(restore_path))
        
        if restore_path:
            print("Restoration mode: Skipped DB initialization (will be loaded from snapshot)")

        # Wait for service to be ready
        await wait_for_service()



        # Upload files or Restore from snapshot
        if restore_path:
            print("\n" + "-" * 50)
            print("PHASE 3: RESTORING FROM SNAPSHOT")
            print("-" * 50)
            snapshot_mgr = SnapshotManager()
            await snapshot_mgr.import_data(restore_path)
            # Idempotently seed any missing seed corpus nodes after importing
            await Database.connect()
            await _seed_corpus_nodes()
            await Database.disconnect()
        else:
            if "files" in init_data:
                uploaded_ids = await upload_files(init_data["files"])
                if uploaded_ids:
                    await wait_for_ingestion(uploaded_ids)
                    
            sample_faqs_path = SCRIPT_DIR / "sample_faqs.json"
            if sample_faqs_path.exists():
                print("\n" + "-" * 50)
                print("PHASE 2.5: SEEDING FAQs")
                print("-" * 50)
                await seed_faqs_main(str(sample_faqs_path))
            else:
                print(f"\nWarning: {sample_faqs_path} not found, skipping FAQ seeding.")

        print("\n" + "=" * 70)
        print("✅ INITIALIZATION COMPLETE!")
        print("=" * 70)
        print(f"\nAI Service: {API_BASE_URL}")
        print(f"API Docs:   {API_BASE_URL}/docs")
        print()

    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    skip = "--skip-confirm" in sys.argv
    restore_file = None
    if "--restore" in sys.argv:
        idx = sys.argv.index("--restore")
        if idx + 1 < len(sys.argv):
            restore_file = sys.argv[idx + 1]
    
    asyncio.run(main(skip_confirm=skip, restore_path=restore_file))

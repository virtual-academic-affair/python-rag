#!/usr/bin/env python3
"""
Database & Storage Initialization Script for AI Service (python-rag).

This script performs a full reset and initialization:
1. Drops MongoDB database
2. Deletes all files from R2 bucket
3. Deletes all stores from Gemini File Search
4. Creates database indexes
5. Seeds system metadata types (academic_year, cohort, access_scope)
6. Creates additional metadata types via API (e.g., department)
7. Creates default store and uploads test files via API

Usage:
    python scripts/init_db.py [--skip-confirm]

Requirements:
    - AI Service must be running on localhost:8000
    - R2 must be running
    - Valid GOOGLE_API_KEY, MONGODB_URL in .env
    - AUTH_TOKEN below must be a valid admin JWT
"""

import asyncio
import json
import os
import sys
import httpx
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

import logging
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
    ".eyJzdWIiOjEsImVtYWlsIjoiYmx1ZWxvb3AudXNAZ21haWwuY29tIiwicm9sZSI6ImFkbWluIiwiaWF0IjoxNzcxOTEzOTgzLCJleHAiOjM3NzcxOTEzOTgzLCJhdWQiOiJ2YWEtYXVkIiwiaXNzIjoidmFhLWlzcyJ9"
    ".RtRCZsru6KuCkHUt06cr0v31z9SG0lWWdOORTo47-j4"
)
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


# ====================================
# Phase 1: Clear existing data
# ====================================

async def drop_mongodb_database():
    """Drop all MongoDB collections."""
    logger.info("Dropping MongoDB database...")

    from motor.motor_asyncio import AsyncIOMotorClient

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

    from r2 import R2
    from r2.error import S3Error

    r2_endpoint = os.getenv("R2_ENDPOINT", "localhost:9000")
    r2_access_key = os.getenv("R2_ACCESS_KEY", "r2admin")
    r2_secret_key = os.getenv("R2_SECRET_KEY", "r2admin")
    r2_bucket = os.getenv("R2_BUCKET_NAME", "rag-files")
    r2_secure = os.getenv("R2_USE_SSL", "false").lower() == "true"

    client = R2(
        r2_endpoint,
        access_key=r2_access_key,
        secret_key=r2_secret_key,
        secure=r2_secure
    )

    try:
        if not client.bucket_exists(r2_bucket):
            logger.info(f"  Bucket '{r2_bucket}' does not exist. Creating...")
            client.make_bucket(r2_bucket)
            logger.info(f"  ✓ Created bucket: {r2_bucket}")
        else:
            objects = client.list_objects(r2_bucket, recursive=True)
            delete_count = 0
            for obj in objects:
                client.remove_object(r2_bucket, obj.object_name)
                delete_count += 1

            if delete_count > 0:
                logger.info(f"  ✓ Deleted {delete_count} files from bucket")
            else:
                logger.info("  Bucket is already empty")

    except S3Error as e:
        logger.warning(f"  R2 error (continuing): {e}")

    logger.info("✅ R2 bucket cleared")


async def delete_all_gemini_stores():
    """Delete all stores from Gemini File Search API."""
    logger.info("Deleting all Gemini File Search stores...")

    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not set in .env")

    client = genai.Client(api_key=api_key)

    try:
        stores = list(client.file_search_stores.list())

        if not stores:
            logger.info("  No Gemini stores found")
        else:
            logger.info(f"  Found {len(stores)} Gemini store(s)")
            for store in stores:
                try:
                    client.file_search_stores.delete(name=store.name, config={"force": True})
                    logger.info(f"  ✓ Deleted: {store.name}")
                except Exception as e:
                    logger.warning(f"  ⚠ Failed to delete {store.name}: {e}")

    except Exception as e:
        logger.warning(f"  Gemini API error (continuing): {e}")

    logger.info("✅ Gemini stores deleted")


# ====================================
# Phase 2: Initialize
# ====================================

async def create_database_indexes():
    """Create MongoDB indexes."""
    logger.info("Creating database indexes...")

    from app.core.database import Database

    await Database.connect()
    db = Database.get_db()

    # Files collection indexes
    await db[Database.FILES].create_index([("store_id", 1)])
    await db[Database.FILES].create_index([("status", 1)])
    await db[Database.FILES].create_index([("created_at", -1)])

    # Metadata types collection indexes
    await db[Database.METADATA_TYPES].create_index([("key", 1)], unique=True)

    # Stores collection indexes
    await db[Database.STORES].create_index([("store_name", 1)], unique=True)
    await db[Database.STORES].create_index([("is_default", 1)])

    await Database.disconnect()
    logger.info("✅ Database indexes created")


async def seed_system_metadata_types():
    """Seed system metadata types (academic_year, cohort, access_scope) directly via service."""
    logger.info("Seeding system metadata types...")

    # Import here so the DB connection from create_database_indexes is not reused
    from app.core.database import Database
    from app.services.rag.metadata_service import MetadataService
    from app.models.database import AllowedValue
    from app.core.exceptions import ConflictException

    await Database.connect()
    metadata_service = MetadataService()

    system_types = [
        {
            "key": "academic_year",
            "display_name": "Năm học",
            "description": "Năm học áp dụng (VD: 2023-2024, 2024-2025). Dùng 'all' cho tất cả năm học.",
            "allowed_values": [
                AllowedValue(value="2022-2023", display_name="2022-2023", is_active=False),
                AllowedValue(value="2023-2024", display_name="2023-2024", is_active=True),
                AllowedValue(value="2024-2025", display_name="2024-2025", is_active=True),
                AllowedValue(value="2025-2026", display_name="2025-2026", is_active=True),
                AllowedValue(value="all", display_name="Tất cả năm học", is_active=True, color="#3498DB"),
            ],
            "is_system": True,
        },
        {
            "key": "cohort",
            "display_name": "Khóa",
            "description": "Khóa sinh viên (VD: K18, K19, K20). Dùng 'all' cho tất cả khóa.",
            "allowed_values": [
                AllowedValue(value="K18", display_name="Khóa 18", is_active=False),
                AllowedValue(value="K19", display_name="Khóa 19", is_active=True),
                AllowedValue(value="K20", display_name="Khóa 20", is_active=True),
                AllowedValue(value="K21", display_name="Khóa 21", is_active=True),
                AllowedValue(value="K22", display_name="Khóa 22", is_active=True),
                AllowedValue(value="all", display_name="Tất cả khóa", is_active=True, color="#3498DB"),
            ],
            "is_system": True,
        },
        {
            "key": "access_scope",
            "display_name": "Phạm vi truy cập",
            "description": "Quyền truy cập tài liệu (công khai cho tất cả, hoặc nội bộ cho staff/admin).",
            "allowed_values": [
                AllowedValue(value="cong_khai", display_name="Công khai", is_active=True, color="#27AE60"),
                AllowedValue(value="noi_bo", display_name="Nội bộ (Staff/Admin)", is_active=True, color="#E74C3C"),
            ],
            "is_system": True,
        },
    ]

    created = 0
    skipped = 0
    for meta_def in system_types:
        key = meta_def["key"]
        try:
            await metadata_service.create_metadata_type(**meta_def)
            logger.info(f"  ✓ Created system metadata: {key}")
            created += 1
        except ConflictException:
            logger.info(f"  ⚠ Already exists (skipped): {key}")
            skipped += 1
        except Exception as e:
            logger.warning(f"  ⚠ Error creating {key}: {e}")

    await Database.disconnect()
    logger.info(f"✅ System metadata seeded: {created} created, {skipped} skipped")


async def create_metadata_types(metadata_types: list):
    """Create non-system metadata types via API (requires admin auth)."""
    logger.info("Creating metadata types via API...")

    async with httpx.AsyncClient(timeout=30) as client:
        for meta in metadata_types:
            try:
                response = await client.post(
                    f"{API_URL}/metadata",
                    json=meta,
                    headers=AUTH_HEADERS
                )
                if response.status_code == 201:
                    logger.info(f"  ✓ Created metadata type: {meta['key']}")
                elif response.status_code == 409:
                    logger.info(f"  ⚠ Metadata type already exists: {meta['key']}")
                else:
                    logger.warning(f"  ⚠ Failed to create {meta['key']}: {response.text}")
            except Exception as e:
                logger.warning(f"  ⚠ Error creating {meta['key']}: {e}")

    logger.info("✅ Metadata types created")


async def create_default_store(store_config: dict) -> str:
    """Create default store via API and return store_id (requires admin auth)."""
    logger.info("Creating default store...")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{API_URL}/stores",
            json=store_config,
            headers=AUTH_HEADERS
        )

        if response.status_code != 201:
            raise Exception(f"Failed to create store: {response.text}")

        data = response.json()
        store_id = data["store_id"]
        store_name = data["store_name"]

        logger.info(f"  ✓ Created store: {store_name}")
        logger.info(f"  ✓ Store ID: {store_id}")

    logger.info("✅ Default store created")
    return store_id


async def upload_files(store_id: str, files_config: list):
    """Upload files via API (requires admin auth)."""
    logger.info("Uploading files...")

    success_count = 0
    fail_count = 0

    async with httpx.AsyncClient(timeout=120) as client:
        for file_config in files_config:
            filename = file_config["filename"]
            display_name = file_config["display_name"]
            metadata = file_config.get("metadata", {})

            file_path = UPLOADS_DIR / filename

            if not file_path.exists():
                logger.warning(f"  ⚠ File not found: {file_path}")
                fail_count += 1
                continue

            try:
                with open(file_path, "rb") as f:
                    files = {"file": (filename, f, "application/octet-stream")}
                    data = {
                        "store_id": store_id,
                        "display_name": display_name,
                        "custom_metadata": json.dumps(metadata),
                    }

                    response = await client.post(
                        f"{API_URL}/files",
                        files=files,
                        data=data,
                        headers=AUTH_HEADERS
                    )

                if response.status_code == 201:
                    result = response.json()
                    logger.info(f"  ✓ Uploaded: {display_name} (ID: {result['file_id']})")
                    success_count += 1
                else:
                    logger.warning(f"  ⚠ Failed to upload {filename}: {response.text}")
                    fail_count += 1

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(f"  ⚠ Error uploading {filename}: {e}")
                fail_count += 1

    logger.info(f"✅ File upload complete: {success_count} success, {fail_count} failed")


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

async def main(skip_confirm: bool = False):
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
        print("   - Gemini stores will be deleted")
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
        await delete_all_gemini_stores()

        # Phase 2: Initialize
        print("\n" + "-" * 50)
        print("PHASE 2: INITIALIZING")
        print("-" * 50)

        await create_database_indexes()
        await seed_system_metadata_types()

        # Wait for service to be ready
        await wait_for_service()

        # Create additional metadata types via API
        if "metadata_types" in init_data and init_data["metadata_types"]:
            await create_metadata_types(init_data["metadata_types"])

        # Create default store
        if "default_store" in init_data:
            store_id = await create_default_store(init_data["default_store"])

            # Upload files
            if "files" in init_data:
                await upload_files(store_id, init_data["files"])

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
    asyncio.run(main(skip_confirm=skip))

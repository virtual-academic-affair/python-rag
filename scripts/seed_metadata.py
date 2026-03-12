"""
Seed System Metadata Types - Phase 4.
Initializes 3 protected system metadata types that cannot be deleted.

Run: python -m scripts.seed_metadata
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.models.database import AllowedValue
from app.services.rag.metadata_service import MetadataService
from app.core.config import Settings
from app.core.database import Database
from app.core.exceptions import ConflictException
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ====================================
# SYSTEM METADATA DEFINITIONS
# ====================================

SYSTEM_METADATA_TYPES = [
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
            AllowedValue(
                value="cong_khai",
                display_name="Công khai",
                is_active=True,
                color="#27AE60"
            ),
            AllowedValue(
                value="noi_bo",
                display_name="Nội bộ (Staff/Admin)",
                is_active=True,
                color="#E74C3C"
            ),
        ],
        "is_system": True,
    },
]


async def seed_system_metadata():
    """Seed 3 system metadata types."""
    settings = Settings()
    await Database.connect()
    metadata_service = MetadataService()
    
    logger.info("=" * 60)
    logger.info("SEEDING SYSTEM METADATA TYPES (Phase 4)")
    logger.info("=" * 60)
    
    created_count = 0
    skipped_count = 0
    
    for meta_def in SYSTEM_METADATA_TYPES:
        key = meta_def["key"]
        try:
            await metadata_service.create_metadata_type(**meta_def)
            logger.info(f"✅ Created system metadata: {key}")
            created_count += 1
        except ConflictException:
            logger.info(f"⏭️  Skipped (already exists): {key}")
            skipped_count += 1
        except Exception as e:
            logger.error(f"❌ Failed to create {key}: {e}", exc_info=True)
    
    logger.info("=" * 60)
    logger.info(f"SEED COMPLETE: {created_count} created, {skipped_count} skipped")
    logger.info("=" * 60 )
    
    # Verify
    all_types = await metadata_service.list_all_metadata_types()
    system_types = [t for t in all_types if t.is_system]
    logger.info(f"\nSystem metadata types in DB: {len(system_types)}")
    for st in system_types:
        allowed_count = len(st.get_allowed_values()) if st.get_allowed_values() else 0
        logger.info(
            f"  - {st.key} ({st.display_name}): "
            f"allowed_values={allowed_count}, "
            f"has_all_value={st.has_all_value}, "
            f"is_system={st.is_system}"
        )
    
    await Database.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(seed_system_metadata())
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Seed failed: {e}", exc_info=True)
        sys.exit(1)

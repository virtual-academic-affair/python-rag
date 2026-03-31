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
from datetime import datetime
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
            AllowedValue(value="2022-2023", display_name="2022-2023", is_active=False, visible_roles=["lecture", "student"]),
            AllowedValue(value="2023-2024", display_name="2023-2024", is_active=True, visible_roles=["lecture", "student"]),
            AllowedValue(value="2024-2025", display_name="2024-2025", is_active=True, visible_roles=["lecture", "student"]),
            AllowedValue(value="2025-2026", display_name="2025-2026", is_active=True, visible_roles=["lecture", "student"]),
            AllowedValue(value="all", display_name="Tất cả năm học", is_active=True, color="#3498DB", visible_roles=["lecture", "student"]),
        ],
        "is_system": True,
    },
    {
        "key": "cohort",
        "display_name": "Khóa",
        "description": "Khóa sinh viên (VD: k18, k19, k20). Dùng 'all' cho tất cả khóa.",
        "allowed_values": [
            AllowedValue(value="k18", display_name="Khóa 18", is_active=False, visible_roles=["lecture", "student"]),
            AllowedValue(value="k19", display_name="Khóa 19", is_active=True, visible_roles=["lecture", "student"]),
            AllowedValue(value="k20", display_name="Khóa 20", is_active=True, visible_roles=["lecture", "student"]),
            AllowedValue(value="k21", display_name="Khóa 21", is_active=True, visible_roles=["lecture", "student"]),
            AllowedValue(value="k22", display_name="Khóa 22", is_active=True, visible_roles=["lecture", "student"]),
            AllowedValue(value="all", display_name="Tất cả khóa", is_active=True, color="#3498DB", visible_roles=["lecture", "student"]),
        ],
        "is_system": True,
    },
    {
        "key": "access_scope",
        "display_name": "Phạm vi truy cập",
        "description": "Quyền truy cập tài liệu: private (chỉ admin), lecture (giảng viên), student (sinh viên). Có thể chọn nhiều.",
        "allowed_values": [
            AllowedValue(
                value="private",
                display_name="Admin Only (Private)",
                is_active=True,
                color="#E74C3C",
                visible_roles=[],          # Only admins see this option
            ),
            AllowedValue(
                value="lecture",
                display_name="Lecture Only",
                is_active=True,
                color="#F39C12",
                visible_roles=[],  # Only admins see this option
            ),
            AllowedValue(
                value="student",
                display_name="Student Only",
                is_active=True,
                color="#27AE60",
                visible_roles=[], # Only admins see this option
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
            # Check if exists
            all_types = await metadata_service.list_all_metadata_types()
            existing = next((t for t in all_types if t.key == key), None)
            
            if existing:
                logger.info(f"🔄 Updating existing system metadata: {key}")
                
                # Apply snake_case to allowed values before updating
                update_values = []
                for v in meta_def.get("allowed_values", []):
                    # v could be an AllowedValue object or a dict
                    val_dict = v.to_dict() if hasattr(v, "to_dict") else dict(v)
                    # ensure value is snake_cased just like in MetadataService
                    from app.services.rag.utils.file_utils import to_snake
                    val_dict["value"] = to_snake(val_dict["value"])
                    update_values.append(val_dict)

                # We use a custom update logic or just overwrite the fields
                await Database.get_db()["metadata_types"].update_one(
                    {"key": key},
                    {"$set": {
                        "display_name": meta_def["display_name"],
                        "description": meta_def["description"],
                        "allowed_values": update_values,
                        "is_system": True,
                        "updated_at": datetime.now()
                    }}
                )
                logger.info(f"✅ Updated system metadata: {key}")
                created_count += 1
            else:
                await metadata_service.create_metadata_type(**meta_def)
                logger.info(f"✅ Created system metadata: {key}")
                created_count += 1
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

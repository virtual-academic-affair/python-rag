"""
Filter Builder - Phase 4.
Builds Gemini filter string from metadata dict with role-based access control.

Logic:
- Single value → exact match: key="value"
- Array value → OR same key: (key="v1" OR key="v2")
- has AllowedValue(value="all") → auto add OR key="all"
- Keys joined with AND
- Enforce access_scope by role:
    * student → access_scope="student"
    * lecture → access_scope="lecture" or "student"
    * admin → no access_scope filter

Uses AllowedValue.value (NOT display_name) for filter string.
"""

import logging
import time
from typing import Dict, Any, Optional, List

from app.models.database import AllowedValue, MetadataTypeDocument
from app.services.rag.metadata_service import MetadataService

logger = logging.getLogger(__name__)

# Cache TTL in seconds (5 minutes)
_CACHE_TTL = 300


class FilterBuilder:
    """
    Builds Gemini metadata filter string from metadata dict.
    Handles role-based access control and has_all_value logic
    (auto-adds OR key='all' when AllowedValue with value='all' exists).
    """
    
    def __init__(self):
        """Initialize filter builder with metadata service."""
        self._metadata_service = None
        self._metadata_types_cache: Optional[Dict[str, MetadataTypeDocument]] = None
        self._cache_loaded_at: float = 0.0
    
    @property
    def metadata_service(self) -> MetadataService:
        """Lazy load metadata service."""
        if self._metadata_service is None:
            self._metadata_service = MetadataService()
        return self._metadata_service
    
    async def _load_metadata_types_cache(self) -> None:
        """Load all metadata types into cache, with TTL-based expiry."""
        now = time.monotonic()
        if self._metadata_types_cache is None or (now - self._cache_loaded_at) > _CACHE_TTL:
            all_types = await self.metadata_service.list_all_metadata_types()
            self._metadata_types_cache = {mt.key: mt for mt in all_types}
            self._cache_loaded_at = now
    
    def _build_key_filter(
        self,
        key: str,
        values: List[str],
        support_all_value: bool
    ) -> str:
        """
        Build filter string for single metadata key.
        
        Args:
            key: Metadata key
            values: List of values (can be single-item list)
            support_all_value: If True, add OR key="all"
        
        Returns:
            Filter string like: key="value" or (key="v1" OR key="v2")
        """
        # Add "all" value if support_all_value is True
        if support_all_value and "all" not in values:
            values = values + ["all"]
        
        # Single value - no parentheses needed
        if len(values) == 1:
            return f'{key}="{values[0]}"'
        
        # Multiple values - wrap in parentheses
        or_parts = [f'{key}="{v}"' for v in values]
        return "(" + " OR ".join(or_parts) + ")"
    
    async def build_filter(
        self,
        metadata: Dict[str, Any],
        user_role: str = "student",
        skip_validation: bool = False
    ) -> str:
        """
        Build Gemini filter string from metadata dict.
        
        Args:
            metadata: Metadata dict (e.g., {"academic_year": "2024-2025", "cohort": ["K20", "K21"]})
            user_role: User role (student, staff, admin) for access_scope enforcement
            skip_validation: If True, skip validation (useful when metadata already validated at upload)
        
        Returns:
            Gemini filter string (e.g., 'access_scope="student" AND (academic_year="2024-2025" OR academic_year="all")')
        
        Raises:
            ValueError: If metadata validation fails (when skip_validation=False)
        
        Note:
            For student role, access_scope is enforced to "student" regardless of input.
            For admin, access_scope filter is removed (can see all documents).
        """
        # Load metadata types cache
        await self._load_metadata_types_cache()
        
        # Validate user-provided metadata BEFORE injecting access_scope
        if not skip_validation and metadata:
            is_valid, errors = await self.metadata_service.validate_metadata(metadata)
            if not is_valid:
                raise ValueError(f"Invalid metadata: {', '.join(errors)}")

        filter_metadata = dict(metadata)
        
        # Enforce access_scope by role AFTER validation
        # This allows injecting a list without triggering strict string validation
        if user_role == "student":
            filter_metadata["access_scope"] = ["student", "both"]
            logger.debug(f"Role={user_role}: enforcing access_scope=['student', 'both']")
        elif user_role == "lecture":
            filter_metadata["access_scope"] = ["lecture", "both"]
            logger.debug(f"Role={user_role}: enforcing access_scope=['lecture', 'both']")
        elif user_role == "admin":
            filter_metadata.pop("access_scope", None)
            logger.debug(f"Role={user_role}: no access_scope filter")
        
        # Build filter parts for each key
        filter_parts = []
        
        for key, value in filter_metadata.items():
            # Get metadata type definition
            meta_type = self._metadata_types_cache.get(key)
            if not meta_type:
                logger.warning(f"Metadata key '{key}' not found in cache, skipping")
                continue
            
            # Convert value to list
            values = value if isinstance(value, list) else [value]
            
            # Build filter for this key
            key_filter = self._build_key_filter(
                key=key,
                values=values,
                support_all_value=meta_type.has_all_value
            )
            filter_parts.append(key_filter)
        
        # Join all parts with AND
        if not filter_parts:
            return ""
        
        filter_string = " AND ".join(filter_parts)
        logger.info(f"Built filter (role={user_role}): {filter_string}")
        return filter_string


    def quick_convert(self, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Convert metadata filter from JSON key-value format to Gemini FileSearch format.
        Simple conversion without DB validation or role-based enforcement.
        Internal helper for cases where metadata is already trusted/validated.

        Input format (JSON):
            {"department": "Đào tạo", "category": "policy"}

        Output format (Gemini):
            'department="Đào tạo" AND category="policy"'
        """
        if not metadata or not isinstance(metadata, dict):
            return None

        logger.debug(f"quick_convert input: {metadata}")
        filter_parts = []
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, str):
                filter_parts.append(f'{key}="{value}"')
            elif isinstance(value, (int, float)):
                filter_parts.append(f'{key}={value}')
            elif isinstance(value, list):
                list_parts = [f'{key}="{v}"' for v in value if isinstance(v, str)]
                if list_parts:
                    filter_parts.append(f"({' OR '.join(list_parts)})")

        filter_string = " AND ".join(filter_parts) if filter_parts else None
        if filter_string:
            logger.info(f"quick_convert result: {filter_string}")
        return filter_string


# ====================================
# SINGLETON INSTANCE
# ====================================

_filter_builder_instance: Optional[FilterBuilder] = None


def get_filter_builder() -> FilterBuilder:
    """Get singleton FilterBuilder instance."""
    global _filter_builder_instance
    if _filter_builder_instance is None:
        _filter_builder_instance = FilterBuilder()
    return _filter_builder_instance


# ====================================
# CONVENIENCE FUNCTIONS
# ====================================

async def build_metadata_filter(
    metadata: Dict[str, Any],
    user_role: str = "student",
    skip_validation: bool = False
) -> str:
    """
    Convenience function to build Gemini filter string with full validation and role enforcement.
    """
    builder = get_filter_builder()
    return await builder.build_filter(metadata, user_role, skip_validation)


def convert_metadata_filter_to_gemini_format(metadata_filter: Optional[Dict[str, Any]]) -> Optional[str]:
    """
    Convenience function for quick conversion without validation.
    """
    return get_filter_builder().quick_convert(metadata_filter)

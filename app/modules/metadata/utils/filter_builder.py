"""
Filter Builder — Fixed Schema version.
Builds Qdrant and MongoDB filters based on the fixed YearRange overlap logic.
"""
import logging
from typing import Dict, Any, Optional

from qdrant_client.http import models as qm

from app.modules.metadata.dtos import UnifiedFilterSchema
from app.modules.metadata.models.value_objects import YEAR_MIN, YEAR_MAX

logger = logging.getLogger(__name__)


class FilterBuilder:
    """
    Builds filters for Qdrant and MongoDB.
    Logic:
    - enrollment_year: range overlap (doc.from <= user_year <= doc.to)
    - academic_year: range overlap
    - type: exact match (if single) or $in match (if array)
    """

    def __init__(self):
        pass

    async def build_qdrant_filter(
        self,
        metadata_filter: Dict[str, Any],
        user_role: str = "student",
        skip_validation: bool = False
    ) -> Optional[qm.Filter]:
        """
        Build metadata query filter for Qdrant.
        Input is expected to be a dict matching the UnifiedFilterSchema.
        """
        if not metadata_filter:
            return None

        try:
            # Use UnifiedFilterSchema which has all optional fields and no defaults
            model = UnifiedFilterSchema.model_validate(metadata_filter)
        except Exception as e:
            logger.warning(f"Invalid metadata filter for Qdrant: {e}")
            return None

        must_conditions = []

        # 1. Enrollment year overlap
        if model.enrollment_year:
            f = model.enrollment_year.from_year
            t = model.enrollment_year.to_year
            must_conditions.extend([
                qm.FieldCondition(
                    key="metadata.enrollment_year_to",
                    range=qm.Range(gte=f)
                ),
                qm.FieldCondition(
                    key="metadata.enrollment_year_from",
                    range=qm.Range(lte=t)
                )
            ])

        # 2. Academic year overlap
        if model.academic_year:
            af = model.academic_year.from_year
            at = model.academic_year.to_year
            must_conditions.extend([
                qm.FieldCondition(
                    key="metadata.academic_year_to",
                    range=qm.Range(gte=af)
                ),
                qm.FieldCondition(
                    key="metadata.academic_year_from",
                    range=qm.Range(lte=at)
                )
            ])

        # 3. Type (Array support)
        if model.type:
            if len(model.type) == 1:
                must_conditions.append(
                    qm.FieldCondition(
                        key="metadata.type",
                        match=qm.MatchValue(value=model.type[0].value)
                    )
                )
            else:
                must_conditions.append(
                    qm.FieldCondition(
                        key="metadata.type",
                        match=qm.MatchAny(any=[t.value for t in model.type])
                    )
                )

        if not must_conditions:
            return None

        return qm.Filter(must=must_conditions)


    async def build_mongo_filter(
        self,
        metadata_filter: Dict[str, Any],
        mongo_prefix: str = "custom_metadata",
        user_role: str = "student",
        skip_validation: bool = False
    ) -> Dict[str, Any]:
        """
        Build metadata query filter for MongoDB filtering.
        """
        if not metadata_filter:
            return {}

        try:
            # Use UnifiedFilterSchema which has all optional fields and no defaults
            model = UnifiedFilterSchema.model_validate(metadata_filter)
        except Exception as e:
            logger.warning(f"Invalid metadata filter for Mongo: {e}")
            return {}

        mongo_filter = {}

        # 1. Enrollment year overlap
        if model.enrollment_year:
            f = model.enrollment_year.from_year
            t = model.enrollment_year.to_year
            mongo_filter[f"{mongo_prefix}.enrollment_year.to_year"] = {"$gte": f}
            mongo_filter[f"{mongo_prefix}.enrollment_year.from_year"] = {"$lte": t}

        # 2. Academic year overlap
        if model.academic_year:
            af = model.academic_year.from_year
            at = model.academic_year.to_year
            mongo_filter[f"{mongo_prefix}.academic_year.to_year"] = {"$gte": af}
            mongo_filter[f"{mongo_prefix}.academic_year.from_year"] = {"$lte": at}

        # 3. Type (Array support)
        if model.type:
            if len(model.type) == 1:
                mongo_filter[f"{mongo_prefix}.type"] = model.type[0].value
            else:
                mongo_filter[f"{mongo_prefix}.type"] = {"$in": [t.value for t in model.type]}

        return mongo_filter


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

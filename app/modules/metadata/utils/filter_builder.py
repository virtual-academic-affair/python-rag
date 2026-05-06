"""
Filter Builder — Fixed Schema version.
Builds Qdrant and MongoDB filters based on the fixed YearRange overlap logic.
"""
import logging
from typing import Dict, Any, Optional

from qdrant_client.http import models as qm

from app.modules.metadata.schemas import FaqMetadataSchema
from app.modules.metadata.models import YEAR_MIN, YEAR_MAX

logger = logging.getLogger(__name__)


class FilterBuilder:
    """
    Builds filters for Qdrant and MongoDB.
    Logic:
    - enrollment_year: range overlap (doc.from <= user_year <= doc.to)
    - academic_year: range overlap
    - type: exact match
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
        Input is expected to be a dict matching the FaqMetadata schema (or InquiryFilters).
        """
        if not metadata_filter:
            return None

        # Parse using FaqMetadataSchema (which supports optional fields)
        try:
            schema = FaqMetadataSchema.model_validate(metadata_filter)
            model = schema.to_model()
        except Exception as e:
            logger.warning(f"Invalid metadata filter for Qdrant: {e}")
            return None

        must_conditions = []

        # 1. Enrollment year overlap
        # user_from <= doc_to AND user_to >= doc_from
        f = model.enrollment_year.from_year
        t = model.enrollment_year.to_year
        if f != YEAR_MIN or t != YEAR_MAX:
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
        af = model.academic_year.from_year
        at = model.academic_year.to_year
        if af != YEAR_MIN or at != YEAR_MAX:
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

        # 3. Type
        model_type = getattr(model, "type", None)
        if model_type:
            must_conditions.append(
                qm.FieldCondition(
                    key="metadata.type",
                    match=qm.MatchValue(value=model_type.value)
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
            schema = FaqMetadataSchema.model_validate(metadata_filter)
            model = schema.to_model()
        except Exception as e:
            logger.warning(f"Invalid metadata filter for Mongo: {e}")
            return {}

        mongo_filter = {}

        # MongoDB stores metadata nested inside a prefix field (e.g. custom_metadata or metadata_filter)
        f = model.enrollment_year.from_year
        t = model.enrollment_year.to_year
        if f != YEAR_MIN or t != YEAR_MAX:
            mongo_filter[f"{mongo_prefix}.enrollment_year.to_year"] = {"$gte": f}
            mongo_filter[f"{mongo_prefix}.enrollment_year.from_year"] = {"$lte": t}

        af = model.academic_year.from_year
        at = model.academic_year.to_year
        if af != YEAR_MIN or at != YEAR_MAX:
            mongo_filter[f"{mongo_prefix}.academic_year.to_year"] = {"$gte": af}
            mongo_filter[f"{mongo_prefix}.academic_year.from_year"] = {"$lte": at}

        model_type = getattr(model, "type", None)
        if model_type:
            mongo_filter[f"{mongo_prefix}.type"] = model_type.value

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

"""Test pure query builders cho pre-filter 3 key (enrollment/academic year + lecturer_only)."""
import pytest

from app.modules.corpus.utils.prefilter import (
    is_privileged,
    build_file_prefilter_query,
    build_faq_prefilter_query,
)

EY = {"enrollment_year": {"from_year": 2022, "to_year": 2022}}


def test_is_privileged_roles():
    assert is_privileged("admin") is True
    assert is_privileged("lecture") is True
    assert is_privileged("student") is False
    assert is_privileged(None) is False       # không truyền role → coi như student
    assert is_privileged("unknown") is False


@pytest.mark.asyncio
async def test_file_query_student_has_status_role_and_strict_year_filter():
    q = await build_file_prefilter_query(EY, "student")
    assert q["status"] == "ready"
    assert q["lecturer_only"] == {"$ne": True}
    assert q["custom_metadata.enrollment_year.to_year"] == {"$gte": 2022}
    assert q["custom_metadata.enrollment_year.from_year"] == {"$lte": 2022}
    assert "$and" not in q


@pytest.mark.asyncio
async def test_file_query_admin_skips_lecturer_only():
    q = await build_file_prefilter_query(EY, "admin")
    assert "lecturer_only" not in q


@pytest.mark.asyncio
async def test_admin_can_filter_exact_lecturer_only_value():
    file_query = await build_file_prefilter_query(EY, "admin", True)
    faq_query = await build_faq_prefilter_query(EY, "admin", False)

    assert file_query["lecturer_only"] is True
    assert faq_query["lecturer_only"] is False


@pytest.mark.asyncio
async def test_student_cannot_opt_into_lecturer_only_content():
    query = await build_file_prefilter_query(EY, "student", True)
    assert query["lecturer_only"] == {"$ne": True}


@pytest.mark.asyncio
async def test_file_query_none_role_filters_like_student():
    q = await build_file_prefilter_query(EY, None)
    assert q["lecturer_only"] == {"$ne": True}


@pytest.mark.asyncio
async def test_faq_query_uses_metadata_filter_prefix_and_top_level_lecturer_only():
    q = await build_faq_prefilter_query(EY, "student")
    assert q["is_active"] is True
    assert q["lecturer_only"] == {"$ne": True}   # cấp document, không nằm trong metadata_filter
    assert q["metadata_filter.enrollment_year.to_year"] == {"$gte": 2022}
    assert q["metadata_filter.enrollment_year.from_year"] == {"$lte": 2022}


@pytest.mark.asyncio
async def test_faq_query_both_year_dims():
    mf = {
        "enrollment_year": {"from_year": 2022, "to_year": 2022},
        "academic_year": {"from_year": 2024, "to_year": 2025},
    }
    q = await build_faq_prefilter_query(mf, "lecture")
    assert q["metadata_filter.enrollment_year.to_year"] == {"$gte": 2022}
    assert q["metadata_filter.academic_year.from_year"] == {"$lte": 2025}
    assert "lecturer_only" not in q

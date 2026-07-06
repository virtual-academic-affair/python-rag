"""Test pure query builders cho pre-filter 3 key (enrollment/academic year + lecturer_only)."""
from app.modules.rag.corpus.utils.prefilter import (
    is_privileged,
    has_year_filter,
    year_overlap_conditions,
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


def test_has_year_filter():
    assert has_year_filter(EY) is True
    assert has_year_filter({"academic_year": {"from_year": 2024, "to_year": 2025}}) is True
    assert has_year_filter({}) is False
    assert has_year_filter(None) is False
    assert has_year_filter({"enrollment_year": None}) is False


def test_year_overlap_conditions_keeps_missing_metadata():
    """Lá thiếu metadata năm vẫn được giữ (nhánh $or None)."""
    conds = year_overlap_conditions(EY, "custom_metadata")
    assert conds == [{
        "$or": [
            {"custom_metadata.enrollment_year": None},
            {
                "custom_metadata.enrollment_year.from_year": {"$lte": 2022},
                "custom_metadata.enrollment_year.to_year": {"$gte": 2022},
            },
        ]
    }]


def test_year_overlap_conditions_empty_when_no_filter():
    assert year_overlap_conditions(None, "custom_metadata") == []
    assert year_overlap_conditions({}, "custom_metadata") == []


def test_file_query_student_has_all_three_keys():
    q = build_file_prefilter_query(EY, "student")
    assert q["status"] == "ready"
    assert q["lecturer_only"] == {"$ne": True}
    assert len(q["$and"]) == 1  # điều kiện enrollment_year


def test_file_query_admin_skips_lecturer_only():
    q = build_file_prefilter_query(EY, "admin")
    assert "lecturer_only" not in q


def test_file_query_none_role_filters_like_student():
    q = build_file_prefilter_query(EY, None)
    assert q["lecturer_only"] == {"$ne": True}


def test_file_query_relax_years_drops_year_conditions_keeps_role():
    q = build_file_prefilter_query(EY, "student", relax_years=True)
    assert "$and" not in q
    assert q["lecturer_only"] == {"$ne": True}   # quyền KHÔNG được nới
    assert q["status"] == "ready"


def test_faq_query_uses_metadata_filter_prefix_and_top_level_lecturer_only():
    q = build_faq_prefilter_query(EY, "student")
    assert q["is_active"] is True
    assert q["lecturer_only"] == {"$ne": True}   # cấp document, không nằm trong metadata_filter
    assert q["$and"][0]["$or"][0] == {"metadata_filter.enrollment_year": None}


def test_faq_query_both_year_dims():
    mf = {
        "enrollment_year": {"from_year": 2022, "to_year": 2022},
        "academic_year": {"from_year": 2024, "to_year": 2025},
    }
    q = build_faq_prefilter_query(mf, "lecture")
    assert len(q["$and"]) == 2
    assert "lecturer_only" not in q

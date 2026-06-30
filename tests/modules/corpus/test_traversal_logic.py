from app.modules.corpus.traversal_logic import classify_leaf, score_candidate, years_overlap


def test_years_overlap():
    assert years_overlap({"from_year": 2020, "to_year": 2024}, {"from_year": 2022, "to_year": 2022})
    assert not years_overlap({"from_year": 2024, "to_year": 2024}, {"from_year": 2022, "to_year": 2022})


def test_classify_keep_on_overlap():
    leaf = {"enrollment_year": {"from_year": 2020, "to_year": 2024}}
    assert classify_leaf(leaf, {"enrollment_year": {"from_year": 2022, "to_year": 2022}}) == "keep"


def test_classify_drop_on_conflict():
    leaf = {"enrollment_year": {"from_year": 2024, "to_year": 2024}}
    assert classify_leaf(leaf, {"enrollment_year": {"from_year": 2022, "to_year": 2022}}) == "drop"


def test_classify_low_when_leaf_missing_metadata():
    assert classify_leaf({}, {"enrollment_year": {"from_year": 2022, "to_year": 2022}}) == "low"


def test_classify_keep_when_no_query_filter():
    assert classify_leaf({"type": "cong_van"}, {}) == "keep"


def test_score_orders_keep_above_low():
    assert score_candidate("keep") > score_candidate("low")
    assert score_candidate("keep", has_topic_match=True) > score_candidate("keep")

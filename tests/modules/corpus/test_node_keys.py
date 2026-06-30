from app.modules.corpus.node_keys import slugify_topic, metadata_node_specs

def test_slugify_topic_vietnamese():
    assert slugify_topic("Chuẩn ngoại ngữ") == "chuan-ngoai-ngu"
    assert slugify_topic("  Tốt   nghiệp ") == "tot-nghiep"
    assert slugify_topic("Đào tạo đại học") == "dao-tao-dai-hoc"

def test_metadata_specs_full():
    specs = metadata_node_specs({
        "type": "quyet_dinh",
        "enrollment_year": {"from_year": 2020, "to_year": 2024},
        "academic_year": {"from_year": 2024, "to_year": 2024},
    })
    keys = {s.node_key for s in specs}
    assert keys == {"type:quyet_dinh", "enrollment_year:2020-2024", "academic_year:2024"}
    by_key = {s.node_key: s for s in specs}
    assert by_key["type:quyet_dinh"].axis_key == "axis:document_types"
    assert by_key["enrollment_year:2020-2024"].axis_key == "axis:enrollment_years"
    assert by_key["academic_year:2024"].axis_key == "axis:academic_years"

def test_metadata_specs_skip_all_years():
    specs = metadata_node_specs({
        "type": "cong_van",
        "enrollment_year": {"from_year": 0, "to_year": 9999},
        "academic_year": {"from_year": 0, "to_year": 9999},
    })
    assert {s.node_key for s in specs} == {"type:cong_van"}

def test_metadata_specs_empty():
    assert metadata_node_specs({}) == []

def test_metadata_specs_partial_year_dict():
    # from_year present but to_year absent → treat missing hi as 9999 (open-ended)
    specs = metadata_node_specs({
        "enrollment_year": {"from_year": 2022},
    })
    assert {s.node_key for s in specs} == {"enrollment_year:2022-9999"}

from app.modules.corpus.data.seed import ROOT_AND_AXES

def test_seed_has_root_and_six_axes():
    keys = {n["node_key"] for n in ROOT_AND_AXES}
    assert "root" in keys
    assert {"axis:documents", "axis:faqs", "axis:topics",
            "axis:document_types", "axis:enrollment_years", "axis:academic_years"} <= keys

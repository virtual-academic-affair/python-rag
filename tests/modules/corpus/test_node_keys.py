from app.modules.corpus.node_keys import slugify_topic, metadata_node_specs

def test_slugify_topic_vietnamese():
    assert slugify_topic("Chuẩn ngoại ngữ") == "chuan-ngoai-ngu"
    assert slugify_topic("  Tốt   nghiệp ") == "tot-nghiep"

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

def test_metadata_specs_skip_all_years():
    specs = metadata_node_specs({
        "type": "cong_van",
        "enrollment_year": {"from_year": 0, "to_year": 9999},
        "academic_year": {"from_year": 0, "to_year": 9999},
    })
    assert {s.node_key for s in specs} == {"type:cong_van"}

def test_metadata_specs_empty():
    assert metadata_node_specs({}) == []

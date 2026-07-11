from app.modules.corpus.services.corpus_service import diff_links


def test_diff_links_add_and_remove():
    add, remove = diff_links(["type:cong_van", "topic:a"], ["type:cong_van", "topic:b"])
    assert add == ["topic:b"]
    assert remove == ["topic:a"]


def test_diff_links_no_change():
    assert diff_links(["x"], ["x"]) == ([], [])


def test_diff_links_from_empty():
    assert diff_links([], ["x", "y"]) == (["x", "y"], [])

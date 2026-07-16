from app.modules.chat.repositories.chat_history_repository import (
    _sanitize_persisted_step,
    _strip_corpus_tree_summaries,
)


def test_strip_corpus_tree_summaries_removes_summary_recursively():
    tree = [
        {
            "nodeKey": "root",
            "title": "Gốc",
            "summary": "Mô tả gốc",
            "children": [
                {
                    "nodeKey": "child",
                    "title": "Con",
                    "summary": "Mô tả con",
                    "children": [],
                },
            ],
        },
    ]

    assert _strip_corpus_tree_summaries(tree) == [
        {
            "nodeKey": "root",
            "title": "Gốc",
            "children": [
                {
                    "nodeKey": "child",
                    "title": "Con",
                    "children": [],
                },
            ],
        },
    ]


def test_sanitize_persisted_step_only_strips_corpus_tree():
    corpus_tree_step = {
        "type": "corpus_tree",
        "content": "Tải cây chủ đề phù hợp.",
        "tree": [{"nodeKey": "root", "title": "Gốc", "summary": "Mô tả", "children": []}],
    }
    traversal_step = {
        "type": "corpus_traversal",
        "action": "expand",
        "nodeKey": "root",
        "content": 'Mở chủ đề "Gốc".',
    }

    assert _sanitize_persisted_step(corpus_tree_step)["tree"] == [
        {"nodeKey": "root", "title": "Gốc", "children": []},
    ]
    assert _sanitize_persisted_step(traversal_step) == traversal_step

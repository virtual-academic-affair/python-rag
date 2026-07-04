from app.modules.corpus.data.seed import SEED_TOPICS, ROOT_AND_AXES


def test_seed_topics_count():
    assert len(SEED_TOPICS) == 20


def test_seed_topics_structure():
    for slug, title, summary in SEED_TOPICS:
        assert slug, "slug must not be empty"
        assert slug == slug.lower(), f"slug must be lowercase: {slug}"
        assert " " not in slug, f"slug must not have spaces: {slug}"
        assert title, "title must not be empty"
        assert summary, "summary must not be empty"


def test_seed_topic_keys_are_unique():
    slugs = [slug for slug, _, _ in SEED_TOPICS]
    assert len(slugs) == len(set(slugs)), "duplicate slugs in SEED_TOPICS"


def test_root_and_axes_unchanged():
    assert len(ROOT_AND_AXES) == 7
    keys = [n["node_key"] for n in ROOT_AND_AXES]
    assert "root" in keys
    assert "axis:topics" in keys

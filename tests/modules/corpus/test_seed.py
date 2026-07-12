from scripts.seed_corpus import SEED_TOPICS
from app.modules.corpus.utils.node_keys import slugify_topic


def test_seed_topics_count():
    # 6 nhóm cha + 20 topic con
    assert len(SEED_TOPICS) == 26


def test_seed_topics_structure():
    for slug, title, summary, parent_slug in SEED_TOPICS:
        assert slug, "slug must not be empty"
        assert slug == slug.lower(), f"slug must be lowercase: {slug}"
        assert " " not in slug, f"slug must not have spaces: {slug}"
        assert title, "title must not be empty"
        assert summary, "summary must not be empty"


def test_seed_slugs_are_unique():
    slugs = [slug for slug, _, _, _ in SEED_TOPICS]
    assert len(slugs) == len(set(slugs)), "duplicate slugs in SEED_TOPICS"


def test_seed_hierarchy_parents_declared_before_children():
    """Cha phải khai báo trước con — seed tạo node theo thứ tự list."""
    seen: set[str] = set()
    for slug, _, _, parent_slug in SEED_TOPICS:
        if parent_slug is not None:
            assert parent_slug in seen, (
                f"parent '{parent_slug}' của '{slug}' phải khai báo trước trong SEED_TOPICS"
            )
        seen.add(slug)


def test_seed_hierarchy_two_levels():
    """Có đúng 6 nhóm cha top-level; mọi topic con trỏ vào một nhóm cha."""
    top_level = [slug for slug, _, _, parent in SEED_TOPICS if parent is None]
    children = [(slug, parent) for slug, _, _, parent in SEED_TOPICS if parent is not None]

    assert len(top_level) == 6
    assert len(children) == 20
    for slug, parent in children:
        assert parent in top_level, f"'{slug}' trỏ vào cha '{parent}' không phải nhóm top-level"


def test_slugify_topic_vietnamese():
    assert slugify_topic("Chuẩn ngoại ngữ") == "chuan-ngoai-ngu"
    assert slugify_topic("  Tốt   nghiệp ") == "tot-nghiep"
    assert slugify_topic("Đào tạo đại học") == "dao-tao-dai-hoc"

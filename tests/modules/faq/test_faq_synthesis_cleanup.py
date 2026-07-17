import pytest

from scripts.seed_faqs import main as seed_faqs
from scripts.snapshot import RETIRED_COLLECTIONS, sanitize_snapshot_documents


def test_snapshot_sanitizes_legacy_faq_data_and_skips_retired_collections():
    documents = [{"_id": "faq-1", "source": "synthesized", "candidate_id": "candidate-1"}]

    assert sanitize_snapshot_documents("faqs", documents) == [
        {"_id": "faq-1", "source": "synthesized"}
    ]
    assert RETIRED_COLLECTIONS == {"faq_candidates", "interaction_logs"}


@pytest.mark.asyncio
async def test_seed_script_rejects_legacy_candidate_input_before_connecting(tmp_path, capsys):
    input_path = tmp_path / "legacy-faqs.json"
    input_path.write_text(
        '{"faqs": [], "candidates": [{"question": "Legacy candidate"}]}',
        encoding="utf-8",
    )

    await seed_faqs(str(input_path))

    assert "FAQ candidates are no longer supported" in capsys.readouterr().out

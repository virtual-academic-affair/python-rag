from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.modules.corpus.dtos import CorpusTraversalRequest, CorpusTraversalResponse
from app.modules.corpus.dtos.topic_out import (
    CorpusFaqRefResponse,
    CorpusFileRefResponse,
    CorpusTopicDetailResponse,
    CorpusTopicSummaryResponse,
    CorpusTreeNodeResponse,
)
from app.modules.corpus.dtos.traverse_corpus import TraversalFileCandidateResponse
from app.modules.metadata.dtos import FileMetadataResponse, YearRangeResponse
from app.modules.rag.query.dtos import RagChatPreviewRequest, TokenUsage


def test_topic_contracts_emit_only_their_intended_camel_case_fields():
    summary = CorpusTopicSummaryResponse(node_key="hoc-phi", parent_key="root", file_count=2)
    detail = CorpusTopicDetailResponse(
        **summary.model_dump(),
        child_keys=["hoc-phi-clc"],
        direct_files=[CorpusFileRefResponse(
            id="file-1",
            name="Quy chế",
            metadata=FileMetadataResponse(
                enrollment_year=YearRangeResponse(from_year=2022, to_year=2022),
                academic_year=YearRangeResponse(from_year=2024, to_year=2025),
                type="cong_van",
            ),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )],
        direct_faqs=[CorpusFaqRefResponse(id="faq-1", name="Học phí?")],
    )
    tree = CorpusTreeNodeResponse(node_key="hoc-phi", direct_files=detail.direct_files)

    assert summary.model_dump(by_alias=True) == {
        "nodeKey": "hoc-phi", "title": "", "summary": "", "parentKey": "root", "fileCount": 2, "faqCount": 0,
    }
    detail_dump = detail.model_dump(by_alias=True, mode="json")
    assert detail_dump["directFiles"][0]["metadata"]["enrollmentYear"]["fromYear"] == 2022
    assert "directFileIds" not in detail_dump
    assert "subtreeFileIds" not in detail_dump
    tree_dump = tree.model_dump(by_alias=True)
    assert "parentKey" not in tree_dump
    assert "childKeys" not in tree_dump
    assert "hasContent" not in tree_dump


def test_traversal_contract_is_strict_and_has_no_duplicate_fields():
    request = CorpusTraversalRequest.model_validate({
        "question": "Điều kiện tốt nghiệp?",
        "role": "student",
        "metadataFilter": {"enrollmentYear": {"fromYear": 2022, "toYear": 2022}},
    })
    response = CorpusTraversalResponse(
        query=request.question,
        role=request.role,
        expanded_node_keys=["topic-1"],
        file_candidates=[TraversalFileCandidateResponse(file_id="file-1", node_key="topic-1")],
        token_usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )
    dumped = response.model_dump(by_alias=True)
    assert dumped["expandedNodeKeys"] == ["topic-1"]
    assert "traversalNodeKeys" not in dumped
    assert "totalFileCandidates" not in dumped
    with pytest.raises(ValidationError):
        CorpusTraversalRequest.model_validate({"question": "q", "enrollmentYear": 2022})


def test_rag_preview_request_is_strict():
    assert RagChatPreviewRequest.model_validate({"question": "q", "enrollmentYear": 2022}).enrollment_year == 2022
    with pytest.raises(ValidationError):
        RagChatPreviewRequest.model_validate({"question": "q", "unexpected": True})

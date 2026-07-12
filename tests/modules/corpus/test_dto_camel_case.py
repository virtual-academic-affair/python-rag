from datetime import datetime, timezone

from app.modules.corpus.dtos import (
    ChatPreviewQueryAnalysis,
    CorpusMetadataFilterResponse,
    CorpusNodeResponse,
    CorpusPayloadRef,
    CorpusPayloadTopicsResponse,
    CorpusPrefilterResponse,
    FaqCandidateResponse,
    FileCandidateResponse,
    TopicCreateRequest,
    TopicMergeRequest,
    PayloadTopicsUpdateRequest,
    TraverseRequest,
    TraverseResponse,
)


def test_corpus_topic_dtos_accept_and_emit_camel_case():
    create = TopicCreateRequest.model_validate({
        "slug": "hoc-phi",
        "title": "Học phí",
        "summary": "Quy định học phí",
        "parentKey": "root",
    })
    merge = TopicMergeRequest.model_validate({"targetKey": "target-topic"})
    response = CorpusNodeResponse(
        node_key="hoc-phi",
        title="Học phí",
        parent_key=create.parent_key,
        child_keys=["hoc-phi-con"],
        file_count=2,
        faq_count=1,
        direct_file_ids=["file-1"],
        direct_faq_ids=["faq-1"],
        direct_files=[CorpusPayloadRef(
            id="file-1",
            name="Quy chế",
            metadata={"enrollmentYear": {"fromYear": 2022, "toYear": 2022}},
            lecturer_only=True,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )],
        direct_faqs=[CorpusPayloadRef(id="faq-1", name="Học phí?")],
        subtree_file_ids=["file-1", "file-2"],
        subtree_faq_ids=["faq-1"],
    )

    assert create.parent_key == "root"
    assert merge.target_key == "target-topic"
    assert response.model_dump(by_alias=True)["nodeKey"] == "hoc-phi"
    assert response.model_dump(by_alias=True)["parentKey"] == "root"
    assert response.model_dump(by_alias=True)["directFileIds"] == ["file-1"]
    assert response.model_dump(by_alias=True, mode="json")["directFiles"][0] == {
        "id": "file-1",
        "name": "Quy chế",
        "metadata": {"enrollmentYear": {"fromYear": 2022, "toYear": 2022}},
        "lecturerOnly": True,
        "updatedAt": "2026-01-01T00:00:00Z",
    }

    update_payload = PayloadTopicsUpdateRequest.model_validate({"nodeKeys": ["topic-a"]})
    payload_response = CorpusPayloadTopicsResponse(
        payload_type="faq",
        payload_id="faq-1",
        name="Học phí?",
        node_keys=update_payload.node_keys,
    )
    assert payload_response.model_dump(by_alias=True) == {
        "payloadType": "faq",
        "payloadId": "faq-1",
        "name": "Học phí?",
        "nodeKeys": ["topic-a"],
    }


def test_corpus_traverse_dtos_accept_and_emit_camel_case():
    request = TraverseRequest.model_validate({
        "question": "Điều kiện tốt nghiệp?",
        "role": "student",
        "metadataFilter": {
            "enrollmentYear": {"fromYear": 2022, "toYear": 2022},
            "academicYear": {"fromYear": 2024, "toYear": 2025},
        },
    })
    response = TraverseResponse(
        query=request.question,
        role=request.role,
        metadata_filter={
            "enrollmentYear": {"fromYear": 2022, "toYear": 2022},
        },
        traversal_node_keys=["topic-1"],
        file_candidates=[FileCandidateResponse(file_id="file-1", node_key="topic-1")],
        faq_candidates=[FaqCandidateResponse(faq_id="faq-1", node_key="topic-1")],
        total_file_candidates=1,
        total_faq_candidates=1,
    )

    assert request.normalized_metadata_filter() == {
        "enrollment_year": {"from_year": 2022, "to_year": 2022},
        "academic_year": {"from_year": 2024, "to_year": 2025},
    }
    dumped = response.model_dump(by_alias=True)
    assert "metadataFilter" in dumped
    assert dumped["fileCandidates"][0]["fileId"] == "file-1"
    assert dumped["fileCandidates"][0]["nodeKey"] == "topic-1"
    assert dumped["faqCandidates"][0]["faqId"] == "faq-1"
    assert dumped["faqCandidates"][0]["nodeKey"] == "topic-1"
    assert dumped["traversalNodeKeys"] == ["topic-1"]
    assert dumped["totalFileCandidates"] == 1
    assert dumped["totalFaqCandidates"] == 1


def test_corpus_debug_converters_emit_camel_case_from_internal_snake_case():
    metadata = CorpusMetadataFilterResponse.from_filter({
        "enrollment_year": {"from_year": 2021, "to_year": 2021},
        "academic_year": {"from_year": 2024, "to_year": 2025},
        "type": ["cong_van"],
    })
    prefilter = CorpusPrefilterResponse.from_trace({
        "allowed_file_count": 2,
        "allowed_faq_count": 1,
    })
    analysis = ChatPreviewQueryAnalysis.from_step({
        "type": "query_analysis",
        "original_question": "Học phí?",
        "effective_question": "Quy định học phí hiện tại?",
        "needs_rag": True,
        "metadata_filter": {
            "enrollment_year": {"from_year": 2021, "to_year": 2021},
        },
    })

    assert metadata.model_dump(by_alias=True)["enrollmentYear"]["fromYear"] == 2021
    assert metadata.model_dump(by_alias=True)["academicYear"]["toYear"] == 2025
    assert prefilter.model_dump(by_alias=True) == {"allowedFileCount": 2, "allowedFaqCount": 1}
    dumped_analysis = analysis.model_dump(by_alias=True)
    assert dumped_analysis["originalQuestion"] == "Học phí?"
    assert dumped_analysis["effectiveQuestion"] == "Quy định học phí hiện tại?"
    assert dumped_analysis["metadataFilter"]["enrollmentYear"]["toYear"] == 2021

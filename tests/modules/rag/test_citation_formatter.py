from app.core.config import settings
from app.modules.rag.query.answering.pageindex_agent.citations import (
    CitationStreamFormatter,
    verify_citations,
)


def _source(file_id: str | None = "file-1") -> dict:
    return {
        "file_id": file_id,
        "file_name": "Quy chế đào tạo",
        "titles": ["Điều 2: Điều kiện tốt nghiệp"],
        "original_url": "https://r2.example.test/original.pdf",
        "markdown_url": "https://r2.example.test/document.md",
    }


def test_verify_citations_always_uses_document_view_url(monkeypatch):
    monkeypatch.setattr(
        settings,
        "DOCUMENT_VIEW_URL_PREFIX",
        "https://vaa.example.test/?viewDocumentId=",
    )

    result = verify_citations(
        "Nội dung (^Điều 2: Điều kiện tốt nghiệp)",
        [_source()],
    )

    assert result == (
        "Nội dung (Xem thêm tại [Điều 2: Điều kiện tốt nghiệp]"
        "(https://vaa.example.test/?viewDocumentId=file-1))"
    )


def test_verify_citations_preserves_marker_when_source_has_no_file_id():
    result = verify_citations(
        "Nội dung (^Điều 2: Điều kiện tốt nghiệp)",
        [_source(file_id=None)],
    )

    assert result == "Nội dung (^Điều 2: Điều kiện tốt nghiệp)"


def test_verify_citations_removes_unmatched_marker():
    result = verify_citations("Nội dung (^Không tồn tại)", [_source()])

    assert result == "Nội dung "


def test_stream_formatter_resolves_citation_split_across_chunks(monkeypatch):
    monkeypatch.setattr(
        settings,
        "DOCUMENT_VIEW_URL_PREFIX",
        "https://vaa.example.test/?viewDocumentId=",
    )
    formatter = CitationStreamFormatter([_source()])

    first = formatter.process_chunk("Nội dung (^Điều 2: Điều kiện")
    second = formatter.process_chunk(" tốt nghiệp)")
    final = formatter.flush()

    assert first + second + final == (
        "Nội dung (Xem thêm tại [Điều 2: Điều kiện tốt nghiệp]"
        "(https://vaa.example.test/?viewDocumentId=file-1))"
    )

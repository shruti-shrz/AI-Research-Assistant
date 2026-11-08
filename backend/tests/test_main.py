"""Tests for app.main – FastAPI endpoint integration via TestClient."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.arxiv import SearchError
from app.llm import LLMError
from app.pdf import PdfError


@pytest.fixture
def api(tmp_db):
    """TestClient backed by a fresh temp database per test."""
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper_row(
    paper_id=1,
    title="Test Paper",
    authors=None,
    year=2024,
    abstract="An abstract.",
    external_id="1234.5678",
    pdf_url="https://arxiv.org/pdf/1234.5678",
    has_full_text=False,
    summary=None,
):
    return {
        "id": paper_id,
        "source": "arxiv",
        "external_id": external_id,
        "title": title,
        "authors": authors or ["Author One"],
        "year": year,
        "abstract": abstract,
        "url": f"https://arxiv.org/abs/{external_id}",
        "pdf_url": pdf_url,
        "has_full_text": has_full_text,
        "summary": summary,
        "created_at": "2024-01-01T00:00:00",
    }


# ---------------------------------------------------------------------------
# GET /api/search
# ---------------------------------------------------------------------------


def test_search_returns_results(api):
    papers = [_make_paper_row()]
    with patch("app.arxiv.search", new=AsyncMock(return_value=papers)):
        response = api.get("/api/search?q=transformers")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert data[0]["external_id"] == "1234.5678"


def test_search_attaches_saved_id_for_library_papers(api):
    # Save a paper so it appears in db.list_papers()
    from app import db
    db.insert_paper(
        source="arxiv",
        title="Saved Paper",
        authors=["A"],
        year=2024,
        abstract="",
        external_id="saved-001",
    )
    result_paper = {**_make_paper_row(), "external_id": "saved-001"}
    with patch("app.arxiv.search", new=AsyncMock(return_value=[result_paper])):
        response = api.get("/api/search?q=saved")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["saved_id"] is not None


def test_search_blank_query_returns_400(api):
    response = api.get("/api/search?q=   ")
    assert response.status_code == 400


def test_search_propagates_arxiv_error_as_502(api):
    with patch("app.arxiv.search", new=AsyncMock(side_effect=SearchError("arXiv down"))):
        response = api.get("/api/search?q=transformers")
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# GET /api/papers
# ---------------------------------------------------------------------------


def test_list_papers_empty(api):
    response = api.get("/api/papers")
    assert response.status_code == 200
    assert response.json() == []


def test_list_papers_returns_saved_papers(api):
    from app import db
    db.insert_paper(
        source="arxiv", title="My Paper", authors=["A"], year=2024,
        abstract="", external_id="list-001",
    )
    response = api.get("/api/papers")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "My Paper"


# ---------------------------------------------------------------------------
# POST /api/papers
# ---------------------------------------------------------------------------


def test_save_paper_creates_record(api):
    payload = {
        "external_id": "2101.00001",
        "title": "New Paper",
        "authors": ["Alice"],
        "year": 2021,
        "abstract": "Abstract here.",
        "url": "https://arxiv.org/abs/2101.00001",
        "pdf_url": "https://arxiv.org/pdf/2101.00001",
    }
    response = api.post("/api/papers", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Paper"
    assert "id" in data


def test_save_paper_duplicate_returns_existing_record(api):
    payload = {
        "external_id": "dupe-001",
        "title": "Paper",
        "authors": [],
        "year": 2024,
        "abstract": "",
    }
    r1 = api.post("/api/papers", json=payload)
    r2 = api.post("/api/papers", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


# ---------------------------------------------------------------------------
# POST /api/papers/upload
# ---------------------------------------------------------------------------


def test_upload_valid_pdf_returns_201(api):
    fake_pdf = b"%PDF-1.4 fake content"
    metadata = {"title": "Uploaded Paper", "authors": ["Bob"], "year": 2023, "abstract": "Abs."}

    with patch("app.pdf.extract_pages", return_value=["Page 1 content"]) as mock_extract, \
         patch("app.llm.extract_metadata", return_value=metadata):
        response = api.post(
            "/api/papers/upload",
            files={"file": ("paper.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["paper"]["title"] == "Uploaded Paper"
    assert data["warning"] is None


def test_upload_non_pdf_file_returns_400(api):
    response = api.post(
        "/api/papers/upload",
        files={"file": ("notes.txt", io.BytesIO(b"plain text"), "text/plain")},
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_upload_oversized_pdf_returns_413(api):
    big_data = b"%PDF" + b"x" * (30 * 1024 * 1024 + 1)
    response = api.post(
        "/api/papers/upload",
        files={"file": ("big.pdf", io.BytesIO(big_data), "application/pdf")},
    )
    assert response.status_code == 413


def test_upload_unreadable_pdf_returns_422(api):
    with patch("app.pdf.extract_pages", side_effect=PdfError("No text found")):
        response = api.post(
            "/api/papers/upload",
            files={"file": ("bad.pdf", io.BytesIO(b"%PDF broken"), "application/pdf")},
        )
    assert response.status_code == 422


def test_upload_llm_failure_falls_back_to_heuristic_metadata(api):
    fake_pdf = b"%PDF-1.4 fake"
    heuristic_meta = {"title": "Guessed Title", "authors": [], "year": None, "abstract": ""}

    with patch("app.pdf.extract_pages", return_value=["Page text"]), \
         patch("app.llm.extract_metadata", side_effect=LLMError("API down")), \
         patch("app.pdf.guess_metadata", return_value=heuristic_meta):
        response = api.post(
            "/api/papers/upload",
            files={"file": ("paper.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["paper"]["title"] == "Guessed Title"
    assert data["warning"] is not None


# ---------------------------------------------------------------------------
# GET /api/papers/{paper_id}
# ---------------------------------------------------------------------------


def test_get_paper_found(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Detailed Paper", authors=["A"], year=2024,
        abstract="", external_id="detail-001",
    )
    response = api.get(f"/api/papers/{paper['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Detailed Paper"
    assert "messages" in data


def test_get_paper_not_found_returns_404(api):
    response = api.get("/api/papers/9999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/papers/{paper_id}
# ---------------------------------------------------------------------------


def test_delete_paper_returns_204(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="To Delete", authors=[], year=2024,
        abstract="", external_id="del-001",
    )
    response = api.delete(f"/api/papers/{paper['id']}")
    assert response.status_code == 204


def test_delete_paper_not_found_returns_404(api):
    response = api.delete("/api/papers/9999")
    assert response.status_code == 404


def test_deleted_paper_no_longer_retrievable(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Gone", authors=[], year=2024, abstract="", external_id="gone-001",
    )
    api.delete(f"/api/papers/{paper['id']}")
    response = api.get(f"/api/papers/{paper['id']}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/papers/{paper_id}/summary
# ---------------------------------------------------------------------------


def test_summarize_returns_summary(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Summary Paper", authors=["A"], year=2024,
        abstract="", external_id="sum-001", full_text="Full paper content here.",
    )
    with patch("app.llm.summarize", return_value="This paper is about X."):
        response = api.post(f"/api/papers/{paper['id']}/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "This paper is about X."
    assert data["basis"] == "full_text"


def test_summarize_uses_abstract_when_no_full_text(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Abstract Only", authors=["A"], year=2024,
        abstract="Just the abstract.", external_id="sum-002",
    )
    with patch("app.llm.summarize", return_value="Summary from abstract."):
        response = api.post(f"/api/papers/{paper['id']}/summary")
    assert response.status_code == 200
    assert response.json()["basis"] == "abstract"


def test_summarize_paper_not_found_returns_404(api):
    response = api.post("/api/papers/9999/summary")
    assert response.status_code == 404


def test_summarize_llm_error_returns_502(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="LLM Fail", authors=[], year=2024,
        abstract="", external_id="sum-003", full_text="Content.",
    )
    with patch("app.llm.summarize", side_effect=LLMError("Claude is down")):
        response = api.post(f"/api/papers/{paper['id']}/summary")
    assert response.status_code == 502


def test_summarize_no_text_returns_422(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Empty Paper", authors=[], year=2024,
        abstract="", external_id="sum-004",
    )
    response = api.post(f"/api/papers/{paper['id']}/summary")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/papers/{paper_id}/ask
# ---------------------------------------------------------------------------


def test_ask_returns_answer(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Ask Paper", authors=["A"], year=2024,
        abstract="", external_id="ask-001", full_text="Paper body.",
    )
    with patch("app.llm.answer", return_value="The answer is 42."):
        response = api.post(
            f"/api/papers/{paper['id']}/ask",
            json={"question": "What is the main contribution?"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "The answer is 42."
    assert data["basis"] == "full_text"


def test_ask_stores_message_history(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Ask Paper 2", authors=[], year=2024,
        abstract="", external_id="ask-002", full_text="Content.",
    )
    with patch("app.llm.answer", return_value="Reply."):
        api.post(f"/api/papers/{paper['id']}/ask", json={"question": "Question 1"})

    messages = db.list_messages(paper["id"])
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Question 1"
    assert messages[1]["role"] == "assistant"


def test_ask_blank_question_returns_400(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Ask Paper 3", authors=[], year=2024,
        abstract="", external_id="ask-003", full_text="Content.",
    )
    response = api.post(f"/api/papers/{paper['id']}/ask", json={"question": "   "})
    assert response.status_code == 400


def test_ask_paper_not_found_returns_404(api):
    response = api.post("/api/papers/9999/ask", json={"question": "What?"})
    assert response.status_code == 404


def test_ask_llm_error_returns_502(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="LLM Fail Ask", authors=[], year=2024,
        abstract="", external_id="ask-004", full_text="Content.",
    )
    with patch("app.llm.answer", side_effect=LLMError("rate limited")):
        response = api.post(f"/api/papers/{paper['id']}/ask", json={"question": "Question?"})
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# DELETE /api/papers/{paper_id}/messages
# ---------------------------------------------------------------------------


def test_clear_chat_returns_204(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Chat Paper", authors=[], year=2024,
        abstract="", external_id="chat-001",
    )
    db.add_message(paper["id"], "user", "Hello")
    response = api.delete(f"/api/papers/{paper['id']}/messages")
    assert response.status_code == 204
    assert db.list_messages(paper["id"]) == []


def test_clear_chat_paper_not_found_returns_404(api):
    response = api.delete("/api/papers/9999/messages")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Lazy PDF download path (_paper_content with pdf_url but no full_text)
# ---------------------------------------------------------------------------


def test_summarize_lazy_downloads_pdf_when_no_full_text(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Lazy PDF Paper", authors=["A"], year=2024,
        abstract="Short abstract.", external_id="lazy-001",
        pdf_url="https://arxiv.org/pdf/lazy-001",
    )
    with (
        patch("app.pdf.download_pdf_text", new=AsyncMock(return_value="Full PDF text content")),
        patch("app.llm.summarize", return_value="Summary from PDF."),
    ):
        response = api.post(f"/api/papers/{paper['id']}/summary")
    assert response.status_code == 200
    assert response.json()["basis"] == "full_text"
    # Should have been persisted for future requests
    assert db.get_full_text(paper["id"]) == "Full PDF text content"


def test_summarize_falls_back_to_abstract_when_pdf_download_fails(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="PDF Fail Paper", authors=["A"], year=2024,
        abstract="Fallback abstract.", external_id="lazy-002",
        pdf_url="https://arxiv.org/pdf/lazy-002",
    )
    with (
        patch("app.pdf.download_pdf_text", new=AsyncMock(side_effect=PdfError("network error"))),
        patch("app.llm.summarize", return_value="Summary from abstract."),
    ):
        response = api.post(f"/api/papers/{paper['id']}/summary")
    assert response.status_code == 200
    assert response.json()["basis"] == "abstract"


def test_ask_lazy_downloads_pdf_when_no_full_text(api):
    from app import db
    paper = db.insert_paper(
        source="arxiv", title="Lazy Ask Paper", authors=["A"], year=2024,
        abstract="Short abstract.", external_id="lazy-003",
        pdf_url="https://arxiv.org/pdf/lazy-003",
    )
    with (
        patch("app.pdf.download_pdf_text", new=AsyncMock(return_value="Full text for QA")),
        patch("app.llm.answer", return_value="Answer from full text."),
    ):
        response = api.post(f"/api/papers/{paper['id']}/ask", json={"question": "What is this?"})
    assert response.status_code == 200
    assert response.json()["answer"] == "Answer from full text."

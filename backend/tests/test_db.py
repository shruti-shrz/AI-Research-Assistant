"""Tests for app.db – SQLite CRUD for papers and messages."""

import sqlite3

import pytest

from app import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert(tmp_db, **overrides):
    kwargs = dict(
        source="arxiv",
        title="Test Paper",
        authors=["Author One"],
        year=2024,
        abstract="An abstract.",
        external_id="1234.5678",
        url="https://arxiv.org/abs/1234.5678",
        pdf_url="https://arxiv.org/pdf/1234.5678",
        full_text=None,
    )
    kwargs.update(overrides)
    return db.insert_paper(**kwargs)


# ---------------------------------------------------------------------------
# list_papers / insert_paper
# ---------------------------------------------------------------------------


def test_list_papers_empty_at_start(tmp_db):
    assert db.list_papers() == []


def test_insert_returns_dict_with_id(tmp_db):
    paper = _insert(tmp_db)
    assert isinstance(paper, dict)
    assert "id" in paper
    assert isinstance(paper["id"], int)


def test_insert_stores_and_retrieves_fields(tmp_db):
    paper = _insert(tmp_db)
    papers = db.list_papers()
    assert len(papers) == 1
    assert papers[0]["title"] == "Test Paper"
    assert papers[0]["year"] == 2024
    assert papers[0]["abstract"] == "An abstract."


def test_insert_deserializes_authors_list(tmp_db):
    paper = _insert(tmp_db, authors=["Alice", "Bob"])
    assert paper["authors"] == ["Alice", "Bob"]


def test_insert_duplicate_external_id_raises_integrity_error(tmp_db):
    _insert(tmp_db, external_id="dupe-001")
    with pytest.raises(sqlite3.IntegrityError):
        _insert(tmp_db, external_id="dupe-001")


def test_insert_null_external_id_allowed_for_multiple_uploads(tmp_db):
    # Uploaded PDFs have no external_id; SQLite UNIQUE allows multiple NULLs
    p1 = _insert(tmp_db, source="upload", external_id=None)
    p2 = _insert(tmp_db, source="upload", external_id=None)
    assert p1["id"] != p2["id"]


def test_list_papers_ordered_newest_first(tmp_db):
    p1 = _insert(tmp_db, title="Older Paper", external_id="id-1")
    p2 = _insert(tmp_db, title="Newer Paper", external_id="id-2")
    papers = db.list_papers()
    ids = [p["id"] for p in papers]
    assert ids.index(p2["id"]) < ids.index(p1["id"])


def test_list_papers_has_full_text_flag_not_full_text(tmp_db):
    _insert(tmp_db, full_text="Big text")
    papers = db.list_papers()
    assert "has_full_text" in papers[0]
    assert "full_text" not in papers[0]


# ---------------------------------------------------------------------------
# get_paper
# ---------------------------------------------------------------------------


def test_get_paper_found(tmp_db):
    paper = _insert(tmp_db)
    result = db.get_paper(paper["id"])
    assert result["id"] == paper["id"]
    assert result["title"] == "Test Paper"


def test_get_paper_not_found_returns_none(tmp_db):
    assert db.get_paper(9999) is None


def test_get_paper_has_full_text_true_when_text_stored(tmp_db):
    paper = _insert(tmp_db, full_text="Some full text")
    result = db.get_paper(paper["id"])
    assert result["has_full_text"] is True


def test_get_paper_has_full_text_false_when_none(tmp_db):
    paper = _insert(tmp_db, full_text=None)
    result = db.get_paper(paper["id"])
    assert result["has_full_text"] is False


# ---------------------------------------------------------------------------
# get_paper_by_external_id
# ---------------------------------------------------------------------------


def test_get_paper_by_external_id_found(tmp_db):
    _insert(tmp_db, external_id="1706.03762")
    result = db.get_paper_by_external_id("1706.03762")
    assert result is not None
    assert result["external_id"] == "1706.03762"


def test_get_paper_by_external_id_not_found_returns_none(tmp_db):
    assert db.get_paper_by_external_id("nonexistent-id") is None


# ---------------------------------------------------------------------------
# get_full_text
# ---------------------------------------------------------------------------


def test_get_full_text_returns_stored_text(tmp_db):
    paper = _insert(tmp_db, full_text="Full paper content here.")
    assert db.get_full_text(paper["id"]) == "Full paper content here."


def test_get_full_text_returns_none_when_not_set(tmp_db):
    paper = _insert(tmp_db, full_text=None)
    assert db.get_full_text(paper["id"]) is None


def test_get_full_text_returns_none_for_missing_paper(tmp_db):
    assert db.get_full_text(9999) is None


# ---------------------------------------------------------------------------
# update_paper
# ---------------------------------------------------------------------------


def test_update_paper_summary(tmp_db):
    paper = _insert(tmp_db)
    db.update_paper(paper["id"], summary="Updated summary.")
    updated = db.get_paper(paper["id"])
    assert updated["summary"] == "Updated summary."


def test_update_paper_full_text(tmp_db):
    paper = _insert(tmp_db)
    db.update_paper(paper["id"], full_text="Extracted text content.")
    assert db.get_full_text(paper["id"]) == "Extracted text content."


def test_update_paper_multiple_fields_at_once(tmp_db):
    paper = _insert(tmp_db)
    db.update_paper(paper["id"], summary="Summary", full_text="Text")
    updated = db.get_paper(paper["id"])
    assert updated["summary"] == "Summary"
    assert db.get_full_text(paper["id"]) == "Text"


def test_update_paper_no_fields_raises_operational_error(tmp_db):
    # update_paper with no keyword args generates "UPDATE papers SET  WHERE id = ?"
    # which is a SQL syntax error — documents the internal API contract
    paper = _insert(tmp_db)
    with pytest.raises(sqlite3.OperationalError):
        db.update_paper(paper["id"])


# ---------------------------------------------------------------------------
# delete_paper
# ---------------------------------------------------------------------------


def test_delete_paper_returns_true_and_removes_record(tmp_db):
    paper = _insert(tmp_db)
    assert db.delete_paper(paper["id"]) is True
    assert db.get_paper(paper["id"]) is None


def test_delete_paper_missing_returns_false(tmp_db):
    assert db.delete_paper(9999) is False


def test_delete_paper_cascades_to_messages(tmp_db):
    paper = _insert(tmp_db)
    db.add_message(paper["id"], "user", "Hello")
    db.delete_paper(paper["id"])
    assert db.list_messages(paper["id"]) == []


def test_delete_paper_does_not_affect_other_papers(tmp_db):
    p1 = _insert(tmp_db, external_id="id-1")
    p2 = _insert(tmp_db, external_id="id-2")
    db.delete_paper(p1["id"])
    assert db.get_paper(p2["id"]) is not None


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


def test_add_and_list_messages(tmp_db):
    paper = _insert(tmp_db)
    db.add_message(paper["id"], "user", "What is this about?")
    db.add_message(paper["id"], "assistant", "It is about transformers.")
    msgs = db.list_messages(paper["id"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "What is this about?"
    assert msgs[1]["role"] == "assistant"


def test_list_messages_empty_when_none_added(tmp_db):
    paper = _insert(tmp_db)
    assert db.list_messages(paper["id"]) == []


def test_clear_messages_removes_all(tmp_db):
    paper = _insert(tmp_db)
    db.add_message(paper["id"], "user", "Question 1")
    db.add_message(paper["id"], "assistant", "Answer 1")
    db.clear_messages(paper["id"])
    assert db.list_messages(paper["id"]) == []


def test_messages_ordered_by_insertion_order(tmp_db):
    paper = _insert(tmp_db)
    for i in range(5):
        db.add_message(paper["id"], "user", f"Message {i}")
    msgs = db.list_messages(paper["id"])
    assert [m["content"] for m in msgs] == [f"Message {i}" for i in range(5)]


def test_messages_isolated_per_paper(tmp_db):
    p1 = _insert(tmp_db, external_id="id-1")
    p2 = _insert(tmp_db, external_id="id-2")
    db.add_message(p1["id"], "user", "Only for paper 1")
    assert db.list_messages(p2["id"]) == []

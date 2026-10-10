"""SQLite storage for the paper library and per-paper chat history."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,              -- 'arxiv' or 'upload'
    external_id TEXT UNIQUE,                -- arXiv id; NULL for uploads
    title       TEXT NOT NULL,
    authors     TEXT NOT NULL DEFAULT '[]', -- JSON list of names
    year        INTEGER,
    abstract    TEXT NOT NULL DEFAULT '',
    url         TEXT,
    pdf_url     TEXT,
    full_text   TEXT,                       -- extracted PDF text, filled lazily for arXiv papers
    summary     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id   INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,               -- 'user' or 'assistant'
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns sent to the frontend. full_text is large, so it is reported as a flag instead.
PUBLIC_COLUMNS = (
    "id, source, external_id, title, authors, year, abstract, url, pdf_url, "
    "summary, created_at, full_text IS NOT NULL AS has_full_text"
)


def init_db() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _paper(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    paper = dict(row)
    paper["authors"] = json.loads(paper["authors"])
    if "has_full_text" in paper:
        paper["has_full_text"] = bool(paper["has_full_text"])
    return paper


def list_papers() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {PUBLIC_COLUMNS} FROM papers ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [_paper(r) for r in rows]


def get_paper(paper_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {PUBLIC_COLUMNS} FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    return _paper(row)


def get_paper_by_external_id(external_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            f"SELECT {PUBLIC_COLUMNS} FROM papers WHERE external_id = ?", (external_id,)
        ).fetchone()
    return _paper(row)


def get_full_text(paper_id: int) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT full_text FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return row["full_text"] if row else None


def insert_paper(
    *,
    source: str,
    title: str,
    authors: list[str],
    year: int | None,
    abstract: str,
    external_id: str | None = None,
    url: str | None = None,
    pdf_url: str | None = None,
    full_text: str | None = None,
) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO papers (source, external_id, title, authors, year, abstract, url, pdf_url, full_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, external_id, title, json.dumps(authors), year, abstract, url, pdf_url, full_text),
        )
        paper_id = cur.lastrowid
    return get_paper(paper_id)


def update_paper(paper_id: int, **fields) -> None:
    assignments = ", ".join(f"{column} = ?" for column in fields)
    with connect() as conn:
        conn.execute(f"UPDATE papers SET {assignments} WHERE id = ?", (*fields.values(), paper_id))


def delete_paper(paper_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    return cur.rowcount > 0


def list_messages(paper_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE paper_id = ? ORDER BY id",
            (paper_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_message(paper_id: int, role: str, content: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (paper_id, role, content) VALUES (?, ?, ?)",
            (paper_id, role, content),
        )


def clear_messages(paper_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM messages WHERE paper_id = ?", (paper_id,))

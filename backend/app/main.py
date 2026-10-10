"""FastAPI backend for the AI Research Assistant."""

import sqlite3
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root before the modules that read environment variables.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import arxiv, db, llm, pdf  # noqa: E402

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
METADATA_PAGES = 3

app = FastAPI(title="AI Research Assistant")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
db.init_db()


class PaperIn(BaseModel):
    external_id: str
    title: str
    authors: list[str] = []
    year: int | None = None
    abstract: str = ""
    url: str | None = None
    pdf_url: str | None = None


class QuestionIn(BaseModel):
    question: str


def _require_paper(paper_id: int) -> dict:
    paper = db.get_paper(paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found.")
    return paper


async def _paper_content(paper: dict) -> tuple[str, str]:
    """Return the text to give the LLM and what it is: 'full_text' or 'abstract'."""
    full_text = db.get_full_text(paper["id"])
    if full_text:
        return full_text, "full_text"
    if paper["pdf_url"]:
        # Papers saved from search only have metadata; fetch the PDF the first time it is needed.
        try:
            full_text = await pdf.download_pdf_text(paper["pdf_url"])
        except pdf.PdfError:
            full_text = None
        if full_text:
            db.update_paper(paper["id"], full_text=full_text)
            return full_text, "full_text"
    if paper["abstract"]:
        return paper["abstract"], "abstract"
    raise HTTPException(422, "This paper has no text to analyze.")


@app.get("/api/search")
async def search(q: str, max_results: int = 10):
    if not q.strip():
        raise HTTPException(400, "Enter a search query.")
    try:
        results = await arxiv.search(q, max_results=min(max(max_results, 1), 50))
    except arxiv.SearchError as exc:
        raise HTTPException(502, str(exc)) from exc
    saved = {p["external_id"]: p["id"] for p in db.list_papers() if p["external_id"]}
    for result in results:
        result["saved_id"] = saved.get(result["external_id"])
    return results


@app.get("/api/papers")
def list_papers():
    return db.list_papers()


@app.post("/api/papers", status_code=201)
def save_paper(paper: PaperIn):
    try:
        return db.insert_paper(source="arxiv", **paper.model_dump())
    except sqlite3.IntegrityError:
        # Already in the library: saving twice is not an error.
        return db.get_paper_by_external_id(paper.external_id)


@app.post("/api/papers/upload", status_code=201)
async def upload_paper(file: UploadFile = File(...)):
    filename = file.filename or "paper.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files can be uploaded.")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The PDF is larger than 30 MB.")
    try:
        pages = pdf.extract_pages(data)
    except pdf.PdfError as exc:
        raise HTTPException(422, str(exc)) from exc

    warning = None
    try:
        metadata = await run_in_threadpool(llm.extract_metadata, pdf.join_pages(pages[:METADATA_PAGES]))
    except llm.LLMError as exc:
        metadata = pdf.guess_metadata(data, pages, filename)
        warning = f"Metadata was extracted without the LLM and may be inaccurate. ({exc})"

    paper = db.insert_paper(
        source="upload",
        title=metadata["title"] or filename,
        authors=metadata["authors"],
        year=metadata["year"],
        abstract=metadata["abstract"],
        full_text=pdf.join_pages(pages),
    )
    (db.UPLOAD_DIR / f"{paper['id']}.pdf").write_bytes(data)
    return {"paper": paper, "warning": warning}


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: int):
    paper = _require_paper(paper_id)
    paper["messages"] = db.list_messages(paper_id)
    return paper


@app.delete("/api/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: int):
    if not db.delete_paper(paper_id):
        raise HTTPException(404, "Paper not found.")
    (db.UPLOAD_DIR / f"{paper_id}.pdf").unlink(missing_ok=True)


@app.post("/api/papers/{paper_id}/summary")
async def summarize(paper_id: int):
    paper = _require_paper(paper_id)
    content, basis = await _paper_content(paper)
    try:
        summary = await run_in_threadpool(llm.summarize, paper, content)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    db.update_paper(paper_id, summary=summary)
    return {"summary": summary, "basis": basis}


@app.post("/api/papers/{paper_id}/ask")
async def ask(paper_id: int, body: QuestionIn):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Enter a question.")
    paper = _require_paper(paper_id)
    content, basis = await _paper_content(paper)
    history = db.list_messages(paper_id)
    try:
        reply = await run_in_threadpool(llm.answer, paper, content, history, question)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    db.add_message(paper_id, "user", question)
    db.add_message(paper_id, "assistant", reply)
    return {"answer": reply, "basis": basis}


@app.delete("/api/papers/{paper_id}/messages", status_code=204)
def clear_chat(paper_id: int):
    _require_paper(paper_id)
    db.clear_messages(paper_id)

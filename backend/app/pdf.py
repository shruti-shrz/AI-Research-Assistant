"""PDF text extraction (PyMuPDF) and a no-LLM fallback for paper metadata."""

import re

import httpx
import pymupdf


class PdfError(Exception):
    pass


def extract_pages(data: bytes) -> list[str]:
    """Return the text of each page."""
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            pages = [page.get_text() for page in doc]
    except Exception as exc:
        raise PdfError("The file could not be read as a PDF.") from exc
    if not any(page.strip() for page in pages):
        raise PdfError("No text could be extracted. The PDF may be a scanned image.")
    return pages


def join_pages(pages: list[str]) -> str:
    return "\n\n".join(page.strip() for page in pages).strip()


async def download_pdf_text(pdf_url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(pdf_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PdfError("The paper's PDF could not be downloaded.") from exc
    return join_pages(extract_pages(response.content))


def guess_metadata(data: bytes, pages: list[str], filename: str) -> dict:
    """Best-effort metadata without an LLM, used when the LLM call is unavailable."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        info = doc.metadata or {}

    first_page = pages[0] if pages else ""
    lines = [line.strip() for line in first_page.splitlines() if line.strip()]

    title = (info.get("title") or "").strip()
    if len(title) < 5:
        title = lines[0] if lines else filename.rsplit(".", 1)[0]

    author_field = (info.get("author") or "").strip()
    authors = [a.strip() for a in re.split(r",|;| and ", author_field) if a.strip()]

    year = None
    match = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", (info.get("creationDate") or "") + " " + first_page)
    if match:
        year = int(match.group(1))

    abstract = ""
    match = re.search(
        r"abstract[\s:.\-—]*(.+?)(?=\n\s*(?:1\.?\s+)?introduction\b|\n\s*keywords\b|\Z)",
        "\n".join(pages[:2]),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        abstract = re.sub(r"\s+", " ", match.group(1)).strip()[:3000]

    return {"title": title, "authors": authors, "year": year, "abstract": abstract}

"""Paper search through the public arXiv API (https://info.arxiv.org/help/api/)."""

import asyncio
import re
import xml.etree.ElementTree as ET

import httpx

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or that the to with we you all".split()
)
# Queries at least this long also get a title-phrase lookup, so a paper searched by name is found.
TITLE_LOOKUP_MIN_WORDS = 3


class SearchError(Exception):
    pass


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _words(query: str) -> list[str]:
    return re.findall(r"[\w\-]+", query.lower())


def _keyword_query(words: list[str]) -> str:
    # arXiv does not index common words, so requiring them matches nothing.
    keywords = [word for word in words if word not in STOPWORDS] or words
    return " AND ".join(f"all:{word}" for word in keywords)


def _parse_entry(entry: ET.Element) -> dict:
    abs_url = _clean(entry.findtext("atom:id", namespaces=ATOM))
    # e.g. http://arxiv.org/abs/1706.03762v7 -> 1706.03762
    arxiv_id = re.sub(r"v\d+$", "", abs_url.rsplit("/abs/", 1)[-1])
    pdf_url = None
    for link in entry.findall("atom:link", ATOM):
        if link.get("title") == "pdf" or link.get("type") == "application/pdf":
            pdf_url = link.get("href")
    published = entry.findtext("atom:published", default="", namespaces=ATOM)
    return {
        "external_id": arxiv_id,
        "source": "arxiv",
        "title": _clean(entry.findtext("atom:title", namespaces=ATOM)),
        "authors": [
            _clean(author.findtext("atom:name", namespaces=ATOM))
            for author in entry.findall("atom:author", ATOM)
        ],
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "abstract": _clean(entry.findtext("atom:summary", namespaces=ATOM)),
        "url": abs_url.replace("http://", "https://"),
        "pdf_url": (pdf_url or f"https://arxiv.org/pdf/{arxiv_id}").replace("http://", "https://"),
    }


async def _fetch(client: httpx.AsyncClient, search_query: str, max_results: int) -> list[dict]:
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        response = await client.get(ARXIV_API, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise SearchError("arXiv is rate limiting requests. Wait a few seconds and try again.") from exc
        raise SearchError(f"arXiv returned an error ({exc.response.status_code}).") from exc
    except httpx.HTTPError as exc:
        raise SearchError("Could not reach arXiv. Check your internet connection.") from exc

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        raise SearchError("arXiv returned a response that could not be read.") from exc
    return [_parse_entry(entry) for entry in root.findall("atom:entry", ATOM)]


async def search(query: str, max_results: int = 10) -> list[dict]:
    words = _words(query)
    if not words:
        return []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        lookups = [_fetch(client, _keyword_query(words), max_results)]
        if len(words) >= TITLE_LOOKUP_MIN_WORDS:
            lookups.append(_fetch(client, f'ti:"{" ".join(words)}"', max_results))
        by_keyword, *by_title = await asyncio.gather(*lookups)

    # Papers whose title is exactly the query come first, then the keyword matches.
    phrase = " ".join(words)
    exact = [p for p in (by_title[0] if by_title else []) if " ".join(_words(p["title"])) == phrase]
    seen = set()
    merged = []
    for paper in exact + by_keyword:
        if paper["external_id"] not in seen:
            seen.add(paper["external_id"])
            merged.append(paper)
    return merged[:max_results]

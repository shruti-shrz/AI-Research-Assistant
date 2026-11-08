"""Tests for app.arxiv – query building, XML parsing, and search."""

import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.arxiv import (
    SearchError,
    _clean,
    _fetch,
    _keyword_query,
    _parse_entry,
    _words,
    search,
)

_NS = "http://www.w3.org/2005/Atom"


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------


def _make_entry(
    arxiv_id="1706.03762",
    title="Test Paper",
    authors=("Author One",),
    published="2017-06-12T17:00:00Z",
    summary="An abstract.",
    pdf_href="https://arxiv.org/pdf/1706.03762",
):
    entry = ET.Element(f"{{{_NS}}}entry")
    ET.SubElement(entry, f"{{{_NS}}}id").text = f"http://arxiv.org/abs/{arxiv_id}v1"
    ET.SubElement(entry, f"{{{_NS}}}title").text = title
    for name in authors:
        a = ET.SubElement(entry, f"{{{_NS}}}author")
        ET.SubElement(a, f"{{{_NS}}}name").text = name
    ET.SubElement(entry, f"{{{_NS}}}published").text = published
    ET.SubElement(entry, f"{{{_NS}}}summary").text = summary
    if pdf_href:
        link = ET.SubElement(entry, f"{{{_NS}}}link")
        link.set("title", "pdf")
        link.set("href", pdf_href)
    return entry


def _make_feed_xml(*entries):
    root = ET.Element(f"{{{_NS}}}feed")
    for e in entries:
        root.append(e)
    return ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------------------------
# _clean
# ---------------------------------------------------------------------------


def test_clean_strips_leading_trailing_whitespace():
    assert _clean("  hello world  ") == "hello world"


def test_clean_collapses_internal_whitespace():
    assert _clean("line1\n  line2") == "line1 line2"


def test_clean_none_returns_empty_string():
    assert _clean(None) == ""


def test_clean_empty_string_returns_empty():
    assert _clean("") == ""


def test_clean_tabs_collapsed():
    assert _clean("a\tb") == "a b"


# ---------------------------------------------------------------------------
# _words
# ---------------------------------------------------------------------------


def test_words_simple_query():
    assert _words("attention mechanism") == ["attention", "mechanism"]


def test_words_lowercases_input():
    assert _words("Transformer Models") == ["transformer", "models"]


def test_words_empty_string():
    assert _words("") == []


def test_words_punctuation_only():
    assert _words("!!! ???") == []


def test_words_includes_hyphens_or_splits():
    result = _words("self-attention")
    # Accepts either "self-attention" as one token or "self" + "attention" as two
    assert "self" in result or "self-attention" in result


# ---------------------------------------------------------------------------
# _keyword_query
# ---------------------------------------------------------------------------


def test_keyword_query_filters_stopwords():
    # "is" and "a" are actual STOPWORDS in arxiv.py; "what" is not
    words = _words("is a transformer")
    query = _keyword_query(words)
    assert "all:transformer" in query
    assert "all:is" not in query
    assert "all:a" not in query
    assert "all:is" not in query


def test_keyword_query_all_stopwords_falls_back_to_full_list():
    # When every word is a stopword the function should still return a non-empty string
    query = _keyword_query(["a", "the"])
    assert query != ""


def test_keyword_query_format_uses_AND():
    query = _keyword_query(["neural", "network"])
    assert query == "all:neural AND all:network"


def test_keyword_query_single_word():
    query = _keyword_query(["transformers"])
    assert query == "all:transformers"


# ---------------------------------------------------------------------------
# _parse_entry
# ---------------------------------------------------------------------------


def test_parse_entry_basic_fields():
    result = _parse_entry(_make_entry())
    assert result["external_id"] == "1706.03762"
    assert result["title"] == "Test Paper"
    assert result["authors"] == ["Author One"]
    assert result["year"] == 2017
    assert result["abstract"] == "An abstract."
    assert result["source"] == "arxiv"


def test_parse_entry_strips_version_suffix():
    result = _parse_entry(_make_entry(arxiv_id="2301.00001"))
    assert result["external_id"] == "2301.00001"
    assert "v" not in result["external_id"]


def test_parse_entry_multiple_authors():
    result = _parse_entry(_make_entry(authors=["Alice", "Bob", "Carol"]))
    assert result["authors"] == ["Alice", "Bob", "Carol"]


def test_parse_entry_no_pdf_link_builds_fallback_url():
    result = _parse_entry(_make_entry(pdf_href=None))
    assert "arxiv.org/pdf" in result["pdf_url"]


def test_parse_entry_missing_published_year_returns_none():
    result = _parse_entry(_make_entry(published=""))
    assert result["year"] is None


def test_parse_entry_non_digit_year_returns_none():
    result = _parse_entry(_make_entry(published="XXXX-01-01T00:00:00Z"))
    assert result["year"] is None


def test_parse_entry_upgrades_http_to_https():
    result = _parse_entry(_make_entry())
    assert result["url"].startswith("https://")
    assert result["pdf_url"].startswith("https://")


def test_parse_entry_pdf_link_detected_by_mime_type():
    # Branch: link.get("type") == "application/pdf" with no title="pdf"
    entry = ET.Element(f"{{{_NS}}}entry")
    ET.SubElement(entry, f"{{{_NS}}}id").text = "http://arxiv.org/abs/9999.9999v1"
    ET.SubElement(entry, f"{{{_NS}}}title").text = "MIME Test Paper"
    a = ET.SubElement(entry, f"{{{_NS}}}author")
    ET.SubElement(a, f"{{{_NS}}}name").text = "Author"
    ET.SubElement(entry, f"{{{_NS}}}published").text = "2024-01-01T00:00:00Z"
    ET.SubElement(entry, f"{{{_NS}}}summary").text = "Abstract."
    link = ET.SubElement(entry, f"{{{_NS}}}link")
    link.set("type", "application/pdf")
    link.set("href", "https://arxiv.org/pdf/9999.9999")

    result = _parse_entry(entry)
    assert result["pdf_url"] == "https://arxiv.org/pdf/9999.9999"


def test_parse_entry_pdf_url_present_in_result():
    result = _parse_entry(_make_entry(pdf_href="https://arxiv.org/pdf/1706.03762"))
    assert result["pdf_url"] == "https://arxiv.org/pdf/1706.03762"


def test_parse_entry_non_pdf_link_uses_constructed_fallback():
    # Branch 42→41: link element exists but matches neither title="pdf" nor
    # type="application/pdf", so pdf_url stays None and the fallback is constructed.
    entry = ET.Element(f"{{{_NS}}}entry")
    ET.SubElement(entry, f"{{{_NS}}}id").text = "http://arxiv.org/abs/2401.00001v1"
    ET.SubElement(entry, f"{{{_NS}}}title").text = "Fallback Test"
    a = ET.SubElement(entry, f"{{{_NS}}}author")
    ET.SubElement(a, f"{{{_NS}}}name").text = "Author"
    ET.SubElement(entry, f"{{{_NS}}}published").text = "2024-01-01T00:00:00Z"
    ET.SubElement(entry, f"{{{_NS}}}summary").text = "Abstract."
    link = ET.SubElement(entry, f"{{{_NS}}}link")
    link.set("rel", "related")          # neither title="pdf" nor type="application/pdf"
    link.set("href", "https://arxiv.org/abs/2401.00001")

    result = _parse_entry(entry)
    assert result["pdf_url"] == "https://arxiv.org/pdf/2401.00001"


# ---------------------------------------------------------------------------
# search – unit tests with _fetch patched
# ---------------------------------------------------------------------------

_SAMPLE_PAPER = {
    "external_id": "1706.03762",
    "source": "arxiv",
    "title": "Attention Is All You Need",
    "authors": ["Vaswani"],
    "year": 2017,
    "abstract": "Abstract.",
    "url": "https://arxiv.org/abs/1706.03762",
    "pdf_url": "https://arxiv.org/pdf/1706.03762",
}


@pytest.fixture
def mock_http_ctx():
    """Provide a no-op httpx.AsyncClient context manager so search() can run."""
    mock_client = AsyncMock()
    with patch("httpx.AsyncClient") as cls:
        cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        cls.return_value.__aexit__ = AsyncMock(return_value=None)
        yield mock_client


async def test_search_returns_results(mock_http_ctx):
    with patch("app.arxiv._fetch", new=AsyncMock(return_value=[_SAMPLE_PAPER])):
        results = await search("attention mechanism", max_results=5)
    assert any(r["external_id"] == "1706.03762" for r in results)


async def test_search_empty_query_returns_empty_list():
    # _words returns [] for whitespace-only input → no HTTP call needed
    results = await search("   ")
    assert results == []


async def test_search_punctuation_only_returns_empty():
    results = await search("!!! ???")
    assert results == []


async def test_search_deduplicates_across_keyword_and_title_lookups(mock_http_ctx):
    # Both lookup strategies return the same paper → should appear only once
    with patch("app.arxiv._fetch", new=AsyncMock(return_value=[_SAMPLE_PAPER])):
        results = await search("attention is all you need", max_results=10)
    ids = [r["external_id"] for r in results]
    assert len(ids) == len(set(ids))


async def test_search_respects_max_results(mock_http_ctx):
    many = [{**_SAMPLE_PAPER, "external_id": str(i)} for i in range(20)]
    with patch("app.arxiv._fetch", new=AsyncMock(return_value=many)):
        results = await search("deep learning", max_results=5)
    assert len(results) <= 5


async def test_search_propagates_search_error(mock_http_ctx):
    with patch("app.arxiv._fetch", new=AsyncMock(side_effect=SearchError("rate limited"))):
        with pytest.raises(SearchError):
            await search("transformers", max_results=5)


async def test_search_short_query_does_not_do_title_lookup(mock_http_ctx):
    # Queries with fewer than TITLE_LOOKUP_MIN_WORDS (3) words skip the title search
    fetch_mock = AsyncMock(return_value=[_SAMPLE_PAPER])
    with patch("app.arxiv._fetch", new=fetch_mock):
        await search("transformers", max_results=5)  # 1 word
    assert fetch_mock.call_count == 1


async def test_search_long_query_does_title_lookup(mock_http_ctx):
    # Queries with ≥ 3 words trigger an extra title search
    fetch_mock = AsyncMock(return_value=[_SAMPLE_PAPER])
    with patch("app.arxiv._fetch", new=fetch_mock):
        await search("attention is needed", max_results=5)  # 3 words
    assert fetch_mock.call_count == 2


async def test_search_exact_title_match_comes_first(mock_http_ctx):
    # A paper whose normalized title exactly equals the query words comes before keyword matches
    exact = {**_SAMPLE_PAPER, "external_id": "exact-001", "title": "Attention Is All You Need"}
    other = {**_SAMPLE_PAPER, "external_id": "other-001", "title": "Some Other Paper"}

    async def fake_fetch(client, query, max_results):
        if query.startswith("ti:"):
            return [exact]
        return [other, exact]

    with patch("app.arxiv._fetch", new=fake_fetch):
        results = await search("attention is all you need", max_results=10)

    assert results[0]["external_id"] == "exact-001"


# ---------------------------------------------------------------------------
# _fetch – direct tests with a mocked httpx client
# ---------------------------------------------------------------------------


async def test_fetch_success_parses_entries():
    feed_xml = _make_feed_xml(_make_entry())
    mock_response = MagicMock()
    mock_response.text = feed_xml
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await _fetch(mock_client, "all:transformers", 5)
    assert len(result) == 1
    assert result[0]["external_id"] == "1706.03762"
    assert result[0]["title"] == "Test Paper"


async def test_fetch_empty_feed_returns_empty_list():
    feed_xml = _make_feed_xml()  # zero entries
    mock_response = MagicMock()
    mock_response.text = feed_xml
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    result = await _fetch(mock_client, "all:noresults", 5)
    assert result == []


async def test_fetch_raises_search_error_on_429():
    bad_response = MagicMock()
    bad_response.status_code = 429
    exc = httpx.HTTPStatusError("", request=MagicMock(), response=bad_response)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=exc)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.raises(SearchError, match="rate limit"):
        await _fetch(mock_client, "all:transformers", 5)


async def test_fetch_raises_search_error_on_other_http_status():
    bad_response = MagicMock()
    bad_response.status_code = 503
    exc = httpx.HTTPStatusError("", request=MagicMock(), response=bad_response)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(side_effect=exc)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.raises(SearchError, match="503"):
        await _fetch(mock_client, "all:transformers", 5)


async def test_fetch_raises_search_error_on_network_connection_failure():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connection reset"))

    with pytest.raises(SearchError, match="internet"):
        await _fetch(mock_client, "all:transformers", 5)


async def test_fetch_raises_search_error_on_malformed_xml():
    mock_response = MagicMock()
    mock_response.text = "this is definitely not xml"
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with pytest.raises(SearchError, match="could not be read"):
        await _fetch(mock_client, "all:transformers", 5)


async def test_fetch_passes_correct_params_to_arxiv_api():
    feed_xml = _make_feed_xml()
    mock_response = MagicMock()
    mock_response.text = feed_xml
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    await _fetch(mock_client, "all:neural AND all:network", 15)

    call_kwargs = mock_client.get.call_args
    params = call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {}))
    assert params["search_query"] == "all:neural AND all:network"
    assert params["max_results"] == 15
    assert params["sortBy"] == "relevance"

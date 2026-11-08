"""Tests for app.llm – Claude API integration."""

import os
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from app.llm import (
    LLMError,
    MAX_PAPER_CHARS,
    _call,
    _client,
    _paper_system,
    _text,
    answer,
    extract_metadata,
    summarize,
)

_PAPER = {"title": "Test Paper", "authors": ["Author A"], "year": 2024}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(text="Mock response text", stop_reason="end_turn"):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


def _make_client(create_response=None, parse_response=None):
    """Return a mock Anthropic client with configurable beta.messages responses."""
    mock_messages = MagicMock()
    mock_messages.create = MagicMock(return_value=create_response or _make_response())
    mock_messages.parse = MagicMock(return_value=parse_response or _make_response())

    mock_beta = MagicMock()
    mock_beta.messages = mock_messages

    mock_client = MagicMock()
    mock_client.beta = mock_beta
    return mock_client


# ---------------------------------------------------------------------------
# _client
# ---------------------------------------------------------------------------


def test_client_raises_llm_error_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        _client()


def test_client_succeeds_with_api_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key-abc123")
    with patch("anthropic.Anthropic"):
        result = _client()
    assert result is not None


# ---------------------------------------------------------------------------
# _text
# ---------------------------------------------------------------------------


def test_text_joins_multiple_text_blocks():
    b1 = MagicMock(); b1.type = "text"; b1.text = "Hello "
    b2 = MagicMock(); b2.type = "text"; b2.text = "world"
    response = MagicMock(); response.content = [b1, b2]
    assert _text(response) == "Hello world"


def test_text_ignores_non_text_blocks():
    text_block = MagicMock(); text_block.type = "text"; text_block.text = "Result"
    tool_block = MagicMock(); tool_block.type = "tool_use"
    response = MagicMock(); response.content = [text_block, tool_block]
    assert _text(response) == "Result"


def test_text_strips_leading_trailing_whitespace():
    b = MagicMock(); b.type = "text"; b.text = "  Trimmed  "
    response = MagicMock(); response.content = [b]
    assert _text(response) == "Trimmed"


def test_text_empty_content_returns_empty_string():
    response = MagicMock(); response.content = []
    assert _text(response) == ""


# ---------------------------------------------------------------------------
# _paper_system
# ---------------------------------------------------------------------------


def test_paper_system_returns_two_blocks():
    system = _paper_system(_PAPER, "Some content")
    assert len(system) == 2


def test_paper_system_first_block_is_reader_instructions():
    system = _paper_system(_PAPER, "Content")
    assert system[0]["type"] == "text"
    assert "research assistant" in system[0]["text"].lower()


def test_paper_system_second_block_contains_paper_title():
    system = _paper_system(_PAPER, "Content")
    assert "Test Paper" in system[1]["text"]


def test_paper_system_second_block_has_cache_control():
    system = _paper_system(_PAPER, "Content")
    assert "cache_control" in system[1]
    assert system[1]["cache_control"]["type"] == "ephemeral"


def test_paper_system_raises_llm_error_when_content_too_long():
    with pytest.raises(LLMError, match="too long"):
        _paper_system(_PAPER, "x" * (MAX_PAPER_CHARS + 1))


def test_paper_system_accepts_content_at_exact_limit():
    # Should not raise at exactly MAX_PAPER_CHARS
    _paper_system(_PAPER, "x" * MAX_PAPER_CHARS)


# ---------------------------------------------------------------------------
# extract_metadata
# ---------------------------------------------------------------------------


def test_extract_metadata_returns_dict(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    parsed = MagicMock()
    parsed.model_dump.return_value = {
        "title": "Paper Title",
        "authors": ["Alice"],
        "year": 2024,
        "abstract": "An abstract.",
    }
    parse_response = _make_response()
    parse_response.parsed_output = parsed

    mock_client = _make_client(parse_response=parse_response)
    with patch("app.llm._client", return_value=mock_client):
        result = extract_metadata("first pages text here")

    assert result["title"] == "Paper Title"
    assert result["year"] == 2024
    assert result["authors"] == ["Alice"]


def test_extract_metadata_raises_when_parsed_output_is_none(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    parse_response = _make_response()
    parse_response.parsed_output = None

    mock_client = _make_client(parse_response=parse_response)
    with patch("app.llm._client", return_value=mock_client):
        with pytest.raises(LLMError, match="did not return"):
            extract_metadata("text")


def test_extract_metadata_propagates_llm_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with patch("app.llm._call", side_effect=LLMError("API rejected")):
        with pytest.raises(LLMError):
            extract_metadata("text")


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------


def test_summarize_returns_text_from_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    mock_client = _make_client(create_response=_make_response("Great paper summary."))

    with patch("app.llm._client", return_value=mock_client):
        result = summarize(_PAPER, "Full paper text content")

    assert result == "Great paper summary."


def test_summarize_raises_llm_error_on_refusal(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    refused = _make_response("", stop_reason="refusal")
    mock_client = _make_client(create_response=refused)

    with patch("app.llm._client", return_value=mock_client):
        with pytest.raises(LLMError, match="declined"):
            summarize(_PAPER, "text")


def test_summarize_raises_on_content_too_long(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with patch("app.llm._client", return_value=_make_client()):
        with pytest.raises(LLMError, match="too long"):
            summarize(_PAPER, "x" * (MAX_PAPER_CHARS + 1))


def test_summarize_propagates_llm_error_from_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with patch("app.llm._call", side_effect=LLMError("rate limited")):
        with pytest.raises(LLMError):
            summarize(_PAPER, "content")


# ---------------------------------------------------------------------------
# answer
# ---------------------------------------------------------------------------


def test_answer_returns_reply_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    mock_client = _make_client(create_response=_make_response("Here is the answer."))

    with patch("app.llm._client", return_value=mock_client):
        result = answer(_PAPER, "content", [], "What is this paper about?")

    assert result == "Here is the answer."


def test_answer_passes_conversation_history(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    mock_client = _make_client(create_response=_make_response("Answer."))

    history = [
        {"role": "user", "content": "Prior question"},
        {"role": "assistant", "content": "Prior answer"},
    ]

    with patch("app.llm._client", return_value=mock_client):
        answer(_PAPER, "content", history, "New question")

    call_kwargs = mock_client.beta.messages.create.call_args
    # Messages: 2 history + 1 new question = 3 total
    messages_sent = call_kwargs.kwargs.get("messages", call_kwargs[1].get("messages", []))
    assert len(messages_sent) == 3
    assert messages_sent[-1]["role"] == "user"
    assert messages_sent[-1]["content"] == "New question"


def test_answer_works_with_empty_history(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    mock_client = _make_client(create_response=_make_response("Cold-start answer."))

    with patch("app.llm._client", return_value=mock_client):
        result = answer(_PAPER, "content", [], "First question ever")

    assert result == "Cold-start answer."


def test_answer_propagates_llm_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with patch("app.llm._call", side_effect=LLMError("connection error")):
        with pytest.raises(LLMError):
            answer(_PAPER, "content", [], "question")


# ---------------------------------------------------------------------------
# _call – direct tests for Anthropic exception → LLMError conversions
# ---------------------------------------------------------------------------


def _api_response(status_code=200):
    """Minimal mock httpx.Response for Anthropic exception constructors."""
    r = MagicMock()
    r.status_code = status_code
    r.headers = {}
    return r


def _api_request():
    return MagicMock()


def test_call_converts_authentication_error_to_llm_error():
    exc = anthropic.AuthenticationError(
        message="Invalid API key", response=_api_response(401), body={}
    )
    fn = MagicMock(side_effect=exc)
    with pytest.raises(LLMError, match="rejected"):
        _call(fn, messages=[], max_tokens=10)


def test_call_converts_rate_limit_error_to_llm_error():
    exc = anthropic.RateLimitError(
        message="Too many requests", response=_api_response(429), body={}
    )
    fn = MagicMock(side_effect=exc)
    with pytest.raises(LLMError, match="rate limit"):
        _call(fn, messages=[], max_tokens=10)


def test_call_converts_api_status_error_to_llm_error():
    exc = anthropic.APIStatusError(
        message="Internal server error", response=_api_response(500), body={}
    )
    fn = MagicMock(side_effect=exc)
    with pytest.raises(LLMError, match="500"):
        _call(fn, messages=[], max_tokens=10)


def test_call_converts_api_connection_error_to_llm_error():
    exc = anthropic.APIConnectionError(request=_api_request())
    fn = MagicMock(side_effect=exc)
    with pytest.raises(LLMError, match="internet"):
        _call(fn, messages=[], max_tokens=10)


def test_call_raises_on_refusal_stop_reason():
    response = _make_response("", stop_reason="refusal")
    fn = MagicMock(return_value=response)
    with pytest.raises(LLMError, match="declined"):
        _call(fn, messages=[], max_tokens=10)


def test_call_returns_response_on_success():
    response = _make_response("All good.", stop_reason="end_turn")
    fn = MagicMock(return_value=response)
    result = _call(fn, messages=[], max_tokens=10)
    assert result is response

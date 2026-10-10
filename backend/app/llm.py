"""Claude integration: metadata extraction, summaries and question answering.

Every other module talks to the LLM through this file, so changing provider or
model only touches this module.
"""

import os

import anthropic
from pydantic import BaseModel

# Haiku is the low-cost default; set CLAUDE_MODEL to a larger model for harder papers.
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")

# On models that support it: if Claude's safety classifiers decline a request, the API
# retries it on a fallback model server-side instead of returning the refusal.
# Haiku has no server-side fallback, so the parameter is left out there.
FALLBACK = (
    {}
    if "haiku" in MODEL
    else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
)

# Roughly 1M tokens of context; a paper longer than this cannot be sent in one request.
MAX_PAPER_CHARS = 2_500_000

READER_INSTRUCTIONS = (
    "You are a research assistant helping a researcher understand a paper. "
    "The paper is given below. Base everything you say on its content. "
    "If the paper does not contain the information needed, say so instead of guessing. "
    "Write in clear plain language and use Markdown for structure where it helps."
)

SUMMARY_PROMPT = (
    "Summarize this paper for a researcher deciding whether to read it in full. Cover: "
    "the problem it addresses, the main idea of the approach, how it was evaluated "
    "(datasets, baselines), the key results, and the main limitations. "
    "Use short sections with headings. Keep it under about 350 words."
)


class LLMError(Exception):
    pass


class PaperMetadata(BaseModel):
    title: str
    authors: list[str]
    year: int | None
    abstract: str


def _client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise LLMError("ANTHROPIC_API_KEY is not set. Add it to the .env file and restart the backend.")
    return anthropic.Anthropic()


def _call(fn, **kwargs):
    """Run an SDK call and turn API failures into a message the UI can show."""
    try:
        response = fn(model=MODEL, **FALLBACK, **kwargs)
    except anthropic.AuthenticationError as exc:
        raise LLMError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Claude is rate limiting requests. Wait a moment and try again.") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Could not reach the Claude API. Check your internet connection.") from exc
    if response.stop_reason == "refusal":
        raise LLMError("Claude declined to process this paper.")
    return response


def _text(response) -> str:
    return "".join(block.text for block in response.content if block.type == "text").strip()


def _paper_system(paper: dict, content: str) -> list[dict]:
    if len(content) > MAX_PAPER_CHARS:
        raise LLMError("This paper is too long to send to the model in one request.")
    header = f"Title: {paper['title']}\nAuthors: {', '.join(paper['authors'])}\nYear: {paper['year']}"
    return [
        {"type": "text", "text": READER_INSTRUCTIONS},
        # The paper is identical across the summary and every question, so cache it:
        # follow-up requests read it at a fraction of the input price.
        {
            "type": "text",
            "text": f"<paper>\n{header}\n\n{content}\n</paper>",
            "cache_control": {"type": "ephemeral"},
        },
    ]


def extract_metadata(first_pages_text: str) -> dict:
    client = _client()
    response = _call(
        client.beta.messages.parse,
        max_tokens=4000,
        output_config={"effort": "low"},
        output_format=PaperMetadata,
        messages=[
            {
                "role": "user",
                "content": (
                    "Below is the text of the first pages of a research paper, extracted from a PDF. "
                    "Extract the paper's title, the list of author names (in order, names only), "
                    "the publication year (null if it is not stated anywhere), and the abstract "
                    "copied verbatim with line breaks and hyphenation from the PDF layout repaired.\n\n"
                    f"<first_pages>\n{first_pages_text}\n</first_pages>"
                ),
            }
        ],
    )
    if response.parsed_output is None:
        raise LLMError("Claude did not return paper metadata.")
    return response.parsed_output.model_dump()


def summarize(paper: dict, content: str) -> str:
    client = _client()
    response = _call(
        client.beta.messages.create,
        max_tokens=8000,
        output_config={"effort": "medium"},
        system=_paper_system(paper, content),
        messages=[{"role": "user", "content": SUMMARY_PROMPT}],
    )
    return _text(response)


def answer(paper: dict, content: str, history: list[dict], question: str) -> str:
    client = _client()
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": question})
    response = _call(
        client.beta.messages.create,
        max_tokens=8000,
        output_config={"effort": "medium"},
        system=_paper_system(paper, content),
        messages=messages,
    )
    return _text(response)

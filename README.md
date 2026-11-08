# AI Research Assistant

A small web application for finding, collecting and understanding research papers.
Search arXiv, save papers to a local library, upload your own PDFs, and use Claude
to summarize a paper or answer questions about it.

## Features

- **Search papers.** Enter keywords or a topic to search arXiv. Each result shows the
  title, authors, publication year, abstract and a link to the paper. Searching for a
  paper by its exact title puts that paper first.
- **Local library.** Save any search result to a SQLite database. Saved papers survive
  page refreshes and application restarts, and can be browsed and removed from the
  Library tab.
- **PDF upload.** Upload a paper as a PDF. The text is extracted with PyMuPDF and Claude
  reads the first pages to pull out the title, authors, year and abstract, so the paper
  is displayed the same way as a search result.
- **Summaries.** Generate a structured summary of a saved paper. The summary is written
  from the full text of the paper: for arXiv papers the PDF is downloaded and its text
  extracted the first time it is needed, then stored.
- **Questions.** Ask questions about a paper in a chat. Follow-up questions keep the
  earlier conversation as context, and the chat history is stored per paper.

## How it is structured

```
backend/                FastAPI application (Python)
  app/main.py           HTTP routes
  app/arxiv.py          paper search through the arXiv API
  app/pdf.py            PDF text extraction (PyMuPDF)
  app/llm.py            all Claude API calls (metadata, summary, Q&A)
  app/db.py             SQLite storage for papers and chat messages
  data/                 created at runtime: library.db and uploaded PDFs (not in git)
  requirements.txt
frontend/               React application (Vite)
  src/App.jsx           tabs and navigation
  src/api.js            calls to the backend
  src/components/       SearchView, LibraryView, PaperDetail, PaperCard
.env.example            template for the API key
```

The browser talks only to the backend. The backend calls two external services: the
arXiv API for search and PDF downloads, and the Anthropic API for Claude. During
development the Vite dev server forwards `/api` requests to the backend on port 8000.

The paper text is sent to Claude as a cached system prompt, so the summary and every
follow-up question about the same paper reuse it at a reduced input price.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/search?q=` | search arXiv |
| GET | `/api/papers` | list saved papers |
| POST | `/api/papers` | save a search result |
| POST | `/api/papers/upload` | upload a PDF |
| GET | `/api/papers/{id}` | one paper with its chat history |
| DELETE | `/api/papers/{id}` | remove a paper |
| POST | `/api/papers/{id}/summary` | generate a summary |
| POST | `/api/papers/{id}/ask` | ask a question |
| DELETE | `/api/papers/{id}/messages` | clear the chat |

## Setup

Requirements: Python 3.11 or newer, Node.js 20 or newer, and an
[Anthropic API key](https://console.anthropic.com/).

1. Create the environment file and add your key:

   ```
   cp .env.example .env
   ```

   Open `.env` and set `ANTHROPIC_API_KEY`. The file is ignored by git.
   `CLAUDE_MODEL` is optional and defaults to `claude-haiku-5-5`, the lowest-cost model.

2. Install the backend:

   ```
   cd backend
   python -m venv .venv
   .venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Install the frontend:

   ```
   cd frontend
   npm install
   ```

## Running

Use two terminals.

Backend, from `backend/` with the virtual environment active:

```
uvicorn app.main:app --port 8000
```

Frontend, from `frontend/`:

```
npm run dev
```

Open http://localhost:5173.

Search, saving and browsing work without an API key. Summaries and questions need the
key. Uploading without a key still works, but the metadata is then guessed from the PDF
with simple rules and is less accurate.

## Testing

The unit test suite lives in two places:

```
backend/tests/                 pytest suite (155 tests)
  conftest.py                  shared fixtures (temporary SQLite database)
  test_arxiv.py                search query building, XML parsing, HTTP errors
  test_db.py                   papers and chat messages CRUD
  test_pdf.py                  text extraction and metadata guessing
  test_llm.py                  Claude calls, error conversion, JSON parsing
  test_main.py                 all 9 HTTP endpoints through TestClient
backend/pytest.ini             pytest configuration (asyncio_mode = auto)
backend/requirements-test.txt  test-only dependencies
frontend/src/__tests__/
  api.test.js                  vitest suite for src/api.js (26 tests)
frontend/vite.config.js        vitest + coverage configuration (test block)
```

No test makes a network call or needs an API key: httpx, the Anthropic SDK and
`fetch` are mocked, and every database test runs against a temporary SQLite file.

### Backend

From `backend/` with the virtual environment active:

```
pip install -r requirements.txt -r requirements-test.txt
python -m pytest -v
```

Coverage with branch coverage:

```
python -m pytest --cov=app --cov-branch --cov-report=term-missing
```

Expected result: 155 passed, 99% coverage (353/353 statements). The one partial branch,
`db.py` 67->69, is unreachable code.

### Frontend

From `frontend/`:

```
npm install
npm test
```

Coverage:

```
npm run test:coverage
```

Expected result: 26 passed, 100% statement, branch, function and line coverage of
`src/api.js`. An HTML/lcov report is written to `frontend/coverage/`.

## Notes and limits

- Search covers arXiv only.
- Scanned PDFs without a text layer cannot be read.
- Uploads are limited to 30 MB.
- If the PDF of an arXiv paper cannot be downloaded, summaries and answers fall back to
  the abstract and the page says so.

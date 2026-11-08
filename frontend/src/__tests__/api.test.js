/**
 * Tests for src/api.js – HTTP client wrapper.
 *
 * Mocks the global `fetch` so no real network traffic is made.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from '../api'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockFetch({ status = 200, body = null, ok = null, throws = false } = {}) {
  const isOk = ok !== null ? ok : status >= 200 && status < 300

  if (throws) {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    return
  }

  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: isOk,
      status,
      json: () => Promise.resolve(body),
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

// ---------------------------------------------------------------------------
// request() internals (via api.search as a representative call)
// ---------------------------------------------------------------------------

describe('request()', () => {
  it('throws when the backend is unreachable', async () => {
    mockFetch({ throws: true })
    await expect(api.search('transformers')).rejects.toThrow('Could not reach the backend')
  })

  it('returns null for a 204 No Content response', async () => {
    mockFetch({ status: 204 })
    const result = await api.clearChat(1)
    expect(result).toBeNull()
  })

  it('throws with detail string from error response', async () => {
    mockFetch({ status: 400, ok: false, body: { detail: 'Enter a search query.' } })
    await expect(api.search('')).rejects.toThrow('Enter a search query.')
  })

  it('throws generic message when error body has no string detail', async () => {
    mockFetch({ status: 500, ok: false, body: { detail: ['list', 'error'] } })
    await expect(api.search('x')).rejects.toThrow('Request failed (500)')
  })

  it('throws generic message when error body is null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: () => Promise.reject(new SyntaxError('no json')),
      }),
    )
    await expect(api.search('x')).rejects.toThrow('Request failed (503)')
  })

  it('returns parsed JSON body on success', async () => {
    const data = [{ external_id: '1706.03762', title: 'Attention' }]
    mockFetch({ body: data })
    const result = await api.search('transformers')
    expect(result).toEqual(data)
  })
})

// ---------------------------------------------------------------------------
// api.search
// ---------------------------------------------------------------------------

describe('api.search', () => {
  it('calls GET /api/search with encoded query', async () => {
    mockFetch({ body: [] })
    await api.search('attention mechanism')
    const url = fetch.mock.calls[0][0]
    expect(url).toContain('/api/search')
    expect(url).toContain(encodeURIComponent('attention mechanism'))
  })

  it('returns the response body directly', async () => {
    const papers = [{ external_id: '1706.03762' }]
    mockFetch({ body: papers })
    const result = await api.search('transformers')
    expect(result).toEqual(papers)
  })
})

// ---------------------------------------------------------------------------
// api.listPapers
// ---------------------------------------------------------------------------

describe('api.listPapers', () => {
  it('calls GET /api/papers', async () => {
    mockFetch({ body: [] })
    await api.listPapers()
    expect(fetch).toHaveBeenCalledWith('/api/papers', undefined)
  })

  it('returns an array', async () => {
    mockFetch({ body: [{ id: 1 }, { id: 2 }] })
    const result = await api.listPapers()
    expect(Array.isArray(result)).toBe(true)
    expect(result).toHaveLength(2)
  })
})

// ---------------------------------------------------------------------------
// api.getPaper
// ---------------------------------------------------------------------------

describe('api.getPaper', () => {
  it('calls GET /api/papers/:id', async () => {
    mockFetch({ body: { id: 7 } })
    await api.getPaper(7)
    expect(fetch).toHaveBeenCalledWith('/api/papers/7', undefined)
  })

  it('returns the paper object', async () => {
    const paper = { id: 7, title: 'Test' }
    mockFetch({ body: paper })
    const result = await api.getPaper(7)
    expect(result).toEqual(paper)
  })
})

// ---------------------------------------------------------------------------
// api.savePaper
// ---------------------------------------------------------------------------

describe('api.savePaper', () => {
  it('calls POST /api/papers with JSON body', async () => {
    const paper = { external_id: '0001.0001', title: 'Paper' }
    mockFetch({ status: 201, body: { id: 1, ...paper } })
    await api.savePaper(paper)

    expect(fetch).toHaveBeenCalledWith(
      '/api/papers',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(paper),
      }),
    )
  })

  it('returns the saved paper', async () => {
    const saved = { id: 42, title: 'Saved Paper' }
    mockFetch({ status: 201, body: saved })
    const result = await api.savePaper({ title: 'Saved Paper' })
    expect(result).toEqual(saved)
  })
})

// ---------------------------------------------------------------------------
// api.deletePaper
// ---------------------------------------------------------------------------

describe('api.deletePaper', () => {
  it('calls DELETE /api/papers/:id', async () => {
    mockFetch({ status: 204 })
    await api.deletePaper(5)
    expect(fetch).toHaveBeenCalledWith(
      '/api/papers/5',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('returns null for a 204', async () => {
    mockFetch({ status: 204 })
    const result = await api.deletePaper(5)
    expect(result).toBeNull()
  })

  it('throws on 404', async () => {
    mockFetch({ status: 404, ok: false, body: { detail: 'Paper not found.' } })
    await expect(api.deletePaper(9999)).rejects.toThrow('Paper not found.')
  })
})

// ---------------------------------------------------------------------------
// api.uploadPdf
// ---------------------------------------------------------------------------

describe('api.uploadPdf', () => {
  it('calls POST /api/papers/upload with FormData', async () => {
    mockFetch({ status: 201, body: { paper: { id: 1 }, warning: null } })
    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'paper.pdf', {
      type: 'application/pdf',
    })
    await api.uploadPdf(file)

    expect(fetch).toHaveBeenCalledWith(
      '/api/papers/upload',
      expect.objectContaining({ method: 'POST' }),
    )
    const [, options] = fetch.mock.calls[0]
    expect(options.body).toBeInstanceOf(FormData)
  })

  it('does not set Content-Type header (browser sets multipart boundary)', async () => {
    mockFetch({ status: 201, body: { paper: { id: 1 }, warning: null } })
    const file = new File(['%PDF'], 'paper.pdf', { type: 'application/pdf' })
    await api.uploadPdf(file)

    const [, options] = fetch.mock.calls[0]
    expect(options.headers).toBeUndefined()
  })
})

// ---------------------------------------------------------------------------
// api.summarize
// ---------------------------------------------------------------------------

describe('api.summarize', () => {
  it('calls POST /api/papers/:id/summary', async () => {
    mockFetch({ body: { summary: 'This paper does X.', basis: 'full_text' } })
    await api.summarize(3)
    expect(fetch).toHaveBeenCalledWith(
      '/api/papers/3/summary',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('returns the summary response', async () => {
    const data = { summary: 'Summary text.', basis: 'abstract' }
    mockFetch({ body: data })
    const result = await api.summarize(3)
    expect(result).toEqual(data)
  })
})

// ---------------------------------------------------------------------------
// api.ask
// ---------------------------------------------------------------------------

describe('api.ask', () => {
  it('calls POST /api/papers/:id/ask with question', async () => {
    mockFetch({ body: { answer: 'The answer.', basis: 'full_text' } })
    await api.ask(2, 'What is the main contribution?')

    expect(fetch).toHaveBeenCalledWith(
      '/api/papers/2/ask',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ question: 'What is the main contribution?' }),
      }),
    )
  })

  it('returns the answer response', async () => {
    const data = { answer: 'Answer here.', basis: 'full_text' }
    mockFetch({ body: data })
    const result = await api.ask(2, 'Question?')
    expect(result).toEqual(data)
  })

  it('throws on 400 blank question error', async () => {
    mockFetch({ status: 400, ok: false, body: { detail: 'Enter a question.' } })
    await expect(api.ask(2, '')).rejects.toThrow('Enter a question.')
  })
})

// ---------------------------------------------------------------------------
// api.clearChat
// ---------------------------------------------------------------------------

describe('api.clearChat', () => {
  it('calls DELETE /api/papers/:id/messages', async () => {
    mockFetch({ status: 204 })
    await api.clearChat(10)
    expect(fetch).toHaveBeenCalledWith(
      '/api/papers/10/messages',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('returns null', async () => {
    mockFetch({ status: 204 })
    const result = await api.clearChat(10)
    expect(result).toBeNull()
  })
})

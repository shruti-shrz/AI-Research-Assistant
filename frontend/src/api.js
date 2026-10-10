async function request(path, options) {
  let response
  try {
    response = await fetch(`/api${path}`, options)
  } catch {
    throw new Error('Could not reach the backend. Is it running on port 8000?')
  }
  if (response.status === 204) return null
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`)
  }
  return body
}

const json = (method, data) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data),
})

export const api = {
  search: (query) => request(`/search?q=${encodeURIComponent(query)}`),
  listPapers: () => request('/papers'),
  getPaper: (id) => request(`/papers/${id}`),
  savePaper: (paper) => request('/papers', json('POST', paper)),
  deletePaper: (id) => request(`/papers/${id}`, { method: 'DELETE' }),
  uploadPdf: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/papers/upload', { method: 'POST', body: form })
  },
  summarize: (id) => request(`/papers/${id}/summary`, { method: 'POST' }),
  ask: (id, question) => request(`/papers/${id}/ask`, json('POST', { question })),
  clearChat: (id) => request(`/papers/${id}/messages`, { method: 'DELETE' }),
}

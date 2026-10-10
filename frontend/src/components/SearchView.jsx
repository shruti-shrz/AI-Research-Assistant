import { useState } from 'react'
import { api } from '../api'
import PaperCard from './PaperCard'

export default function SearchView({ onOpenPaper, onLibraryChanged }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [savingId, setSavingId] = useState(null)

  async function runSearch(event) {
    event.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    try {
      setResults(await api.search(query))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function save(paper) {
    setSavingId(paper.external_id)
    setError('')
    try {
      const saved = await api.savePaper(paper)
      setResults((current) =>
        current.map((r) => (r.external_id === paper.external_id ? { ...r, saved_id: saved.id } : r)),
      )
      onLibraryChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setSavingId(null)
    }
  }

  return (
    <section>
      <form className="searchbar" onSubmit={runSearch}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search arXiv by keywords or topic, e.g. retrieval augmented generation"
          aria-label="Search query"
          autoFocus
        />
        <button className="primary" disabled={loading}>{loading ? 'Searching…' : 'Search'}</button>
      </form>

      {error && <p className="error">{error}</p>}
      {results === null && !loading && !error && (
        <p className="empty">Search for a topic to find papers, then save the ones you want to study.</p>
      )}
      {results?.length === 0 && <p className="empty">No papers found. Try different keywords.</p>}

      {results?.map((paper) => (
        <PaperCard key={paper.external_id} paper={paper}>
          {paper.saved_id ? (
            <>
              <span className="saved">✓ Saved</span>
              <button onClick={() => onOpenPaper(paper.saved_id)}>Open in library</button>
            </>
          ) : (
            <button className="primary" disabled={savingId === paper.external_id} onClick={() => save(paper)}>
              {savingId === paper.external_id ? 'Saving…' : 'Save to library'}
            </button>
          )}
        </PaperCard>
      ))}
    </section>
  )
}

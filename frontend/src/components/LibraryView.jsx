import { useRef, useState } from 'react'
import { api } from '../api'
import PaperCard from './PaperCard'

export default function LibraryView({ papers, loadError, onOpenPaper, onLibraryChanged }) {
  const fileInput = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function upload(event) {
    const file = event.target.files[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    setError('')
    setNotice('')
    try {
      const { paper, warning } = await api.uploadPdf(file)
      setNotice(warning || `Added “${paper.title}” to your library.`)
      onLibraryChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  async function remove(paper) {
    if (!window.confirm(`Remove “${paper.title}” from your library?`)) return
    setError('')
    try {
      await api.deletePaper(paper.id)
      onLibraryChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section>
      <div className="toolbar">
        <h2>Saved papers ({papers.length})</h2>
        <input ref={fileInput} type="file" accept="application/pdf,.pdf" hidden onChange={upload} />
        <button className="primary" disabled={uploading} onClick={() => fileInput.current.click()}>
          {uploading ? 'Reading PDF…' : 'Upload PDF'}
        </button>
      </div>

      {(error || loadError) && <p className="error">{error || loadError}</p>}
      {notice && <p className="notice">{notice}</p>}
      {papers.length === 0 && !loadError && (
        <p className="empty">Your library is empty. Save papers from Search or upload a PDF.</p>
      )}

      {papers.map((paper) => (
        <PaperCard key={paper.id} paper={paper} onOpen={() => onOpenPaper(paper.id)}>
          <button className="primary" onClick={() => onOpenPaper(paper.id)}>Summarize &amp; ask</button>
          <button className="danger" onClick={() => remove(paper)}>Remove</button>
        </PaperCard>
      ))}
    </section>
  )
}

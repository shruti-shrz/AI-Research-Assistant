import { useState } from 'react'

const ABSTRACT_PREVIEW = 320

export function PaperMeta({ paper }) {
  const authors = paper.authors.length ? paper.authors.join(', ') : 'Unknown authors'
  return (
    <p className="meta">
      {authors} · {paper.year ?? 'Year unknown'}
      <span className={`badge ${paper.source}`}>{paper.source === 'upload' ? 'Uploaded PDF' : 'arXiv'}</span>
    </p>
  )
}

export default function PaperCard({ paper, onOpen, children }) {
  const [expanded, setExpanded] = useState(false)
  const abstract = paper.abstract || 'No abstract available.'
  const isLong = abstract.length > ABSTRACT_PREVIEW
  const shown = expanded || !isLong ? abstract : `${abstract.slice(0, ABSTRACT_PREVIEW)}…`

  return (
    <article className="card">
      <h3>
        {onOpen ? (
          <button className="link title" onClick={onOpen}>{paper.title}</button>
        ) : (
          paper.title
        )}
      </h3>
      <PaperMeta paper={paper} />
      <p className="abstract">
        {shown}{' '}
        {isLong && (
          <button className="link" onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </p>
      <div className="actions">
        {paper.url && <a href={paper.url} target="_blank" rel="noreferrer">View paper ↗</a>}
        {children}
      </div>
    </article>
  )
}

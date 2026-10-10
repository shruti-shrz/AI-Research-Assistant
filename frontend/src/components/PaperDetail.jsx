import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { api } from '../api'
import { PaperMeta } from './PaperCard'

const EXAMPLE_QUESTIONS = [
  'What problem does this paper address?',
  'What is the main idea of the proposed approach?',
  'What datasets are used?',
  'What are the major limitations?',
  'How does this method compare with the baselines?',
]

const ABSTRACT_ONLY_NOTE =
  'The full text of this paper could not be retrieved, so this is based on the abstract only.'

export default function PaperDetail({ paperId, onBack }) {
  const [paper, setPaper] = useState(null)
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [summarizing, setSummarizing] = useState(false)
  const [asking, setAsking] = useState(false)
  const [abstractOnly, setAbstractOnly] = useState(false)
  const [error, setError] = useState('')
  const chatEnd = useRef(null)

  useEffect(() => {
    let cancelled = false
    api
      .getPaper(paperId)
      .then((data) => {
        if (cancelled) return
        setPaper(data)
        setMessages(data.messages)
      })
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [paperId])

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, asking])

  async function summarize() {
    setSummarizing(true)
    setError('')
    try {
      const { summary, basis } = await api.summarize(paperId)
      setPaper((current) => ({ ...current, summary }))
      setAbstractOnly(basis === 'abstract')
    } catch (err) {
      setError(err.message)
    } finally {
      setSummarizing(false)
    }
  }

  async function ask(text) {
    const asked = text.trim()
    if (!asked || asking) return
    setAsking(true)
    setError('')
    setQuestion('')
    setMessages((current) => [...current, { role: 'user', content: asked }])
    try {
      const { answer, basis } = await api.ask(paperId, asked)
      setMessages((current) => [...current, { role: 'assistant', content: answer }])
      setAbstractOnly(basis === 'abstract')
    } catch (err) {
      // The question was not stored, so take it back out and let the user retry.
      setMessages((current) => current.slice(0, -1))
      setQuestion(asked)
      setError(err.message)
    } finally {
      setAsking(false)
    }
  }

  async function clearChat() {
    setError('')
    try {
      await api.clearChat(paperId)
      setMessages([])
    } catch (err) {
      setError(err.message)
    }
  }

  if (!paper) {
    return (
      <section>
        <button className="link" onClick={onBack}>← Back to library</button>
        {error ? <p className="error">{error}</p> : <p className="empty">Loading…</p>}
      </section>
    )
  }

  return (
    <section>
      <button className="link" onClick={onBack}>← Back to library</button>

      <article className="card">
        <h2>{paper.title}</h2>
        <PaperMeta paper={paper} />
        <p className="abstract">{paper.abstract || 'No abstract available.'}</p>
        {paper.url && (
          <div className="actions">
            <a href={paper.url} target="_blank" rel="noreferrer">View paper ↗</a>
          </div>
        )}
      </article>

      {error && <p className="error">{error}</p>}
      {abstractOnly && <p className="notice">{ABSTRACT_ONLY_NOTE}</p>}

      <article className="card">
        <div className="toolbar">
          <h3>Summary</h3>
          <button className="primary" disabled={summarizing} onClick={summarize}>
            {summarizing ? 'Reading the paper…' : paper.summary ? 'Regenerate' : 'Generate summary'}
          </button>
        </div>
        {paper.summary ? (
          <div className="markdown"><Markdown>{paper.summary}</Markdown></div>
        ) : (
          <p className="empty">
            {summarizing
              ? 'Claude is reading the full paper. This can take up to a minute.'
              : 'No summary yet. Generate one from the full text of the paper.'}
          </p>
        )}
      </article>

      <article className="card">
        <div className="toolbar">
          <h3>Ask about this paper</h3>
          {messages.length > 0 && <button onClick={clearChat} disabled={asking}>Clear chat</button>}
        </div>

        <div className="chat">
          {messages.map((message, index) => (
            <div key={index} className={`bubble ${message.role}`}>
              {message.role === 'assistant' ? (
                <div className="markdown"><Markdown>{message.content}</Markdown></div>
              ) : (
                message.content
              )}
            </div>
          ))}
          {asking && <div className="bubble assistant pending">Thinking…</div>}
          <div ref={chatEnd} />
        </div>

        {messages.length === 0 && (
          <div className="chips">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button key={example} disabled={asking} onClick={() => ask(example)}>{example}</button>
            ))}
          </div>
        )}

        <form
          className="searchbar"
          onSubmit={(event) => {
            event.preventDefault()
            ask(question)
          }}
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about this paper"
            aria-label="Question"
          />
          <button className="primary" disabled={asking || !question.trim()}>Ask</button>
        </form>
      </article>
    </section>
  )
}

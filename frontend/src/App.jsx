import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import LibraryView from './components/LibraryView'
import PaperDetail from './components/PaperDetail'
import SearchView from './components/SearchView'

export default function App() {
  const [tab, setTab] = useState('search')
  const [openPaperId, setOpenPaperId] = useState(null)
  const [papers, setPapers] = useState([])
  const [loadError, setLoadError] = useState('')

  const refreshLibrary = useCallback(() => {
    api
      .listPapers()
      .then((data) => {
        setPapers(data)
        setLoadError('')
      })
      .catch((err) => setLoadError(err.message))
  }, [])

  useEffect(refreshLibrary, [refreshLibrary])

  function showTab(next) {
    setTab(next)
    setOpenPaperId(null)
  }

  function openPaper(id) {
    setTab('library')
    setOpenPaperId(id)
  }

  return (
    <>
      <header>
        <h1>AI Research Assistant</h1>
        <nav>
          <button className={tab === 'search' ? 'active' : ''} onClick={() => showTab('search')}>
            Search
          </button>
          <button className={tab === 'library' ? 'active' : ''} onClick={() => showTab('library')}>
            Library ({papers.length})
          </button>
        </nav>
      </header>

      <main>
        {/* Search stays mounted so results survive a trip to the library. */}
        <div hidden={tab !== 'search'}>
          <SearchView onOpenPaper={openPaper} onLibraryChanged={refreshLibrary} />
        </div>
        {tab === 'library' &&
          (openPaperId ? (
            <PaperDetail key={openPaperId} paperId={openPaperId} onBack={() => setOpenPaperId(null)} />
          ) : (
            <LibraryView
              papers={papers}
              loadError={loadError}
              onOpenPaper={openPaper}
              onLibraryChanged={refreshLibrary}
            />
          ))}
      </main>
    </>
  )
}

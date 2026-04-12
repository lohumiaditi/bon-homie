import { useState } from 'react'
import SearchForm from './components/SearchForm.jsx'
import ResultsList from './components/ResultsList.jsx'

const API = '/api'

export default function App() {
  const [sessionId, setSessionId] = useState(null)
  const [view, setView] = useState('form') // 'form' | 'results'

  async function handleSearch(prefs) {
    const res = await fetch(`${API}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs),
    })
    const data = await res.json()
    setSessionId(data.session_id)
    setView('results')
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center gap-3">
          <span className="text-3xl">🏠</span>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Flat Hunter</h1>
            <p className="text-xs text-gray-500">Pune · Powered by AI agents</p>
          </div>
          {view === 'results' && (
            <button
              onClick={() => { setView('form'); setSessionId(null) }}
              className="ml-auto text-sm text-blue-600 hover:underline"
            >
              ← New Search
            </button>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        {view === 'form' && <SearchForm onSearch={handleSearch} />}
        {view === 'results' && <ResultsList sessionId={sessionId} apiBase={API} />}
      </main>
    </div>
  )
}

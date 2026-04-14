import { useState } from 'react'
import SearchForm from './components/SearchForm.jsx'
import ResultsList from './components/ResultsList.jsx'
import LoginButton from './components/LoginButton.jsx'
import { useAuth } from './contexts/AuthContext.jsx'

const API = '/api'

export default function App() {
  const { user, loading } = useAuth()
  const [sessionId, setSessionId] = useState(null)
  const [view, setView] = useState('form') // 'form' | 'results'

  async function handleSearch(prefs) {
    const res = await fetch(`${API}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',           // send JWT cookie automatically
      body: JSON.stringify(prefs),
    })
    const data = await res.json()
    setSessionId(data.session_id)
    setView('results')
  }

  // ── Loading splash ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="text-5xl mb-4">🏠</div>
          <p className="text-gray-500 text-sm animate-pulse">Loading Flat Hunter…</p>
        </div>
      </div>
    )
  }

  // ── Login gate ────────────────────────────────────────────────────────────
  if (!user) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-lg p-10 max-w-sm w-full text-center">
          <div className="text-6xl mb-4">🏠</div>
          <h1 className="text-2xl font-bold text-gray-900 mb-1">Flat Hunter</h1>
          <p className="text-gray-500 text-sm mb-8">
            Find your perfect flat in Pune — AI-powered, Metro-aware.
          </p>

          {/* Security badges */}
          <div className="flex justify-center gap-4 mb-8 text-xs text-gray-400">
            <span className="flex items-center gap-1">
              <span>🔒</span> End-to-end encrypted
            </span>
            <span className="flex items-center gap-1">
              <span>🛡️</span> CSRF protected
            </span>
          </div>

          <div className="flex justify-center">
            <LoginButton />
          </div>

          <p className="text-xs text-gray-400 mt-6 leading-relaxed">
            We only request your <strong>name</strong> and <strong>email</strong>.
            No posts are read or written without your action.
            Your data is encrypted at rest and never sold.
          </p>
        </div>
      </div>
    )
  }

  // ── Main app (authenticated) ──────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-3">
          <span className="text-3xl">🏠</span>
          <div>
            <h1 className="text-xl font-bold text-gray-900">Flat Hunter</h1>
            <p className="text-xs text-gray-500">Pune · Powered by AI agents</p>
          </div>

          {view === 'results' && (
            <button
              onClick={() => { setView('form'); setSessionId(null) }}
              className="ml-auto mr-2 text-sm text-blue-600 hover:underline"
            >
              ← New Search
            </button>
          )}

          {/* User avatar / logout — pushed to the right */}
          <div className={view !== 'results' ? 'ml-auto' : ''}>
            <LoginButton />
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        {view === 'form'    && <SearchForm onSearch={handleSearch} />}
        {view === 'results' && <ResultsList sessionId={sessionId} apiBase={API} />}
      </main>
    </div>
  )
}

import { useState, useEffect, useRef } from 'react'
import ListingCard from './ListingCard.jsx'

const STATUS_MESSAGES = {
  queued: 'Search queued...',
  scraping: 'Scraping listings from 6 platforms...',
  filtering: 'Filtering by your preferences...',
  ranking: 'Finding metro stations & ranking results...',
  done: 'Done!',
  error: 'Something went wrong.',
}

export default function ResultsList({ sessionId, apiBase }) {
  const [status, setStatus] = useState({ status: 'queued', message: 'Starting...', progress: 0 })
  const [listings, setListings] = useState([])
  const [loadedResults, setLoadedResults] = useState(false)
  const pollRef = useRef(null)

  useEffect(() => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${apiBase}/status/${sessionId}`)
        const data = await res.json()
        setStatus(data)

        if (data.status === 'done' && !loadedResults) {
          clearInterval(pollRef.current)
          fetchResults()
        }
        if (data.status === 'error') {
          clearInterval(pollRef.current)
        }
      } catch (e) {
        console.error('Status poll error:', e)
      }
    }, 3000)

    return () => clearInterval(pollRef.current)
  }, [sessionId, loadedResults])

  async function fetchResults() {
    try {
      const res = await fetch(`${apiBase}/results/${sessionId}`)
      const data = await res.json()
      setListings(data.listings || [])
      setLoadedResults(true)
    } catch (e) {
      console.error('Fetch results error:', e)
    }
  }

  const isDone = status.status === 'done'
  const isError = status.status === 'error'

  return (
    <div>
      {/* Progress bar */}
      {!isDone && !isError && (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 mb-6 max-w-2xl mx-auto">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-gray-700 font-medium">{status.message}</p>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${status.progress}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 mt-2 text-right">{status.progress}%</p>

          <div className="mt-4 grid grid-cols-3 gap-2 text-xs text-center text-gray-400">
            {['scraping', 'filtering', 'ranking'].map(step => (
              <div key={step} className={`py-2 px-1 rounded-lg ${status.status === step ? 'bg-blue-50 text-blue-600 font-medium' : ''}`}>
                {step === 'scraping' && '🕷 Scraping'}
                {step === 'filtering' && '🔍 Filtering'}
                {step === 'ranking' && '🏆 Ranking'}
              </div>
            ))}
          </div>
        </div>
      )}

      {isError && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-6 mb-6 text-center">
          <p className="text-red-600 font-medium">⚠ {status.message}</p>
          <p className="text-xs text-red-400 mt-1">Check that your .env API keys are correct and try again.</p>
        </div>
      )}

      {/* Results */}
      {isDone && (
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-800">
            {listings.length > 0 ? `${listings.length} Flats Found` : 'No results found'}
          </h2>
          <p className="text-xs text-gray-400">Sorted by metro proximity + price</p>
        </div>
      )}

      {listings.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {listings.map(l => (
            <ListingCard key={l.id} listing={l} apiBase={apiBase} />
          ))}
        </div>
      )}

      {isDone && listings.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-4xl mb-3">🏘</p>
          <p className="font-medium">No listings found matching your criteria.</p>
          <p className="text-sm mt-1">Try relaxing your filters (budget, area, furnishing).</p>
        </div>
      )}
    </div>
  )
}

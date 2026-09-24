import { useCallback, useEffect, useState } from 'react'
import { api, timeAgo, whatsappUrl, card } from './api.js'

const FILTERS = [
  { value: 'new', label: 'New' },
  { value: 'shortlisted', label: 'Shortlisted' },
  { value: 'contacted', label: 'Contacted' },
  { value: 'dismissed', label: 'Dismissed' },
  { value: '', label: 'All' },
]

const ACTIONS = {
  new:         ['shortlisted', 'contacted', 'dismissed'],
  shortlisted: ['contacted', 'dismissed'],
  contacted:   ['shortlisted', 'dismissed'],
  dismissed:   ['new'],
}
const ACTION_LABEL = { shortlisted: '★ Shortlist', contacted: '✓ Contacted', dismissed: 'Dismiss', new: 'Restore' }

function LeadRow({ lead, onStatus }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <li className="py-4 flex gap-4">
      {lead.images?.[0] && (
        <img src={lead.images[0]} alt="" className="w-20 h-20 rounded-lg object-cover flex-shrink-0 bg-gray-100"
          onError={e => { e.target.style.display = 'none' }} />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1">
          <span className="font-bold text-blue-600">
            {lead.price ? `₹${lead.price.toLocaleString('en-IN')}/mo` : 'Price not stated'}
          </span>
          <span className="text-sm text-gray-600">📍 {lead.area_name || 'Pune'}</span>
          {lead.furnishing && <span className="text-xs text-gray-500">{lead.furnishing}</span>}
          {lead.gender && <span className="text-xs text-gray-500">{lead.gender} only</span>}
          <span className="text-xs text-gray-400 ml-auto">{timeAgo(lead.created_at)}</span>
        </div>
        <p className={`text-sm text-gray-700 whitespace-pre-line ${expanded ? '' : 'line-clamp-3'}`}>{lead.text}</p>
        {lead.text?.length > 220 && (
          <button onClick={() => setExpanded(x => !x)} className="text-xs text-blue-600 hover:underline">
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
        <div className="flex flex-wrap items-center gap-2 mt-2">
          {lead.contact && (
            <a href={whatsappUrl(lead.contact, lead)} target="_blank" rel="noreferrer"
              className="text-xs font-semibold bg-green-500 hover:bg-green-600 text-white px-3 py-1.5 rounded-lg">
              💬 WhatsApp {lead.contact}
            </a>
          )}
          {lead.url && (
            <a href={lead.url} target="_blank" rel="noreferrer"
              className="text-xs border border-gray-200 text-gray-600 hover:bg-gray-50 px-3 py-1.5 rounded-lg">
              Open post
            </a>
          )}
          {lead.poster_url && (
            <a href={lead.poster_url} target="_blank" rel="noreferrer"
              className="text-xs text-gray-500 hover:text-blue-600">
              by {lead.poster_name || 'poster'}
            </a>
          )}
          <span className="ml-auto flex gap-1">
            {(ACTIONS[lead.status] || []).map(s => (
              <button key={s} onClick={() => onStatus(lead, s)}
                className="text-xs text-gray-600 hover:bg-gray-100 px-2 py-1 rounded-md">
                {ACTION_LABEL[s]}
              </button>
            ))}
          </span>
        </div>
      </div>
    </li>
  )
}

export default function LeadsCard({ refreshKey }) {
  const [filter, setFilter] = useState('new')
  const [leads, setLeads] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api(`/facebook/leads${filter ? `?status=${filter}` : ''}`)
      setLeads(data.leads)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { load() }, [load, refreshKey])

  async function setStatus(lead, status) {
    try {
      await api(`/facebook/leads/${lead.id}`, { method: 'PATCH', body: { status } })
      setLeads(ls => filter ? ls.filter(l => l.id !== lead.id) : ls.map(l => l.id === lead.id ? { ...l, status } : l))
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className={card}>
      <div className="flex flex-wrap items-center gap-3 mb-2">
        <h2 className="text-lg font-bold text-gray-900">Leads</h2>
        <div className="flex flex-wrap gap-1 sm:ml-auto">
          {FILTERS.map(f => (
            <button key={f.label} onClick={() => setFilter(f.value)}
              className={`text-xs px-3 py-1.5 rounded-full font-medium transition
                ${filter === f.value ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-gray-400 mb-2">
        Group posts offering a flat or room. Posts from people who are looking for a flat are left out.
      </p>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {loading ? (
        <p className="text-sm text-gray-400 py-6 text-center animate-pulse">Loading leads…</p>
      ) : leads.length === 0 ? (
        <p className="text-sm text-gray-400 py-6 text-center">No {filter || ''} leads yet.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {leads.map(l => <LeadRow key={l.id} lead={l} onStatus={setStatus} />)}
        </ul>
      )}
    </section>
  )
}

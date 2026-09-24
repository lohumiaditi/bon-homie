import { useState } from 'react'
import { api, timeAgo, card, btnPrimary, btnGhost } from './api.js'

const STATUS = {
  active:     { label: 'Connected',            cls: 'bg-green-100 text-green-700' },
  unverified: { label: 'Connected · checking', cls: 'bg-amber-100 text-amber-700' },
  expired:    { label: 'Session expired',      cls: 'bg-red-100 text-red-700' },
}

function CookieForm({ onConnected, submitLabel }) {
  const [cookies, setCookies] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onConnected(await api('/facebook/connect', { method: 'POST', body: { cookies } }))
      setCookies('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <ol className="text-sm text-gray-600 space-y-1.5 list-decimal list-inside">
        <li>Open <strong>facebook.com</strong> in a private/incognito window and log in with the account the agent should use.</li>
        <li>
          Copy its cookies: with the <strong>Cookie-Editor</strong> extension click <em>Export → JSON</em>,
          or in DevTools → Application → Cookies copy the <code>c_user</code> and <code>xs</code> values
          as <code>c_user=…; xs=…</code>.
        </li>
        <li>Paste below, then close the window <strong>without logging out</strong> (logging out ends the session).</li>
      </ol>
      <textarea
        value={cookies}
        onChange={e => setCookies(e.target.value)}
        rows={4}
        placeholder='[{"name":"c_user","value":"1000…"}, …]   or   c_user=1000…; xs=…'
        className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={busy || !cookies.trim()} className={btnPrimary}>
          {busy ? 'Checking…' : submitLabel}
        </button>
        <p className="text-xs text-gray-400">
          🔒 Encrypted at rest. Used only to read rental groups for you. Disconnect any time.
        </p>
      </div>
    </form>
  )
}

function Toggle({ checked, onChange, label, hint }) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)}
        className="mt-1 w-4 h-4 accent-blue-600" />
      <span>
        <span className="text-sm font-medium text-gray-800">{label}</span>
        {hint && <span className="block text-xs text-gray-500">{hint}</span>}
      </span>
    </label>
  )
}

export default function ConnectCard({ conn, onChange }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function act(label, fn) {
    setBusy(label)
    setError('')
    try {
      onChange(await fn())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const updateSetting = (field, value) =>
    act(field, () => api('/facebook/connection', { method: 'PATCH', body: { [field]: value } }))

  if (!conn?.connected) {
    return (
      <section className={card}>
        <h2 className="text-lg font-bold text-gray-900 mb-1">Connect your Facebook</h2>
        <p className="text-sm text-gray-500 mb-4">
          Facebook doesn't let apps read groups any more, so the agent browses them as you.
          Connect the account that's in (or should join) Pune rental groups.
        </p>
        <CookieForm onConnected={onChange} submitLabel="Connect Facebook" />
      </section>
    )
  }

  const status = STATUS[conn.status] || STATUS.unverified
  return (
    <section className={card}>
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <h2 className="text-lg font-bold text-gray-900">Facebook</h2>
        <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${status.cls}`}>{status.label}</span>
        <span className="text-xs text-gray-400">
          Account {conn.fb_user_id} · checked {timeAgo(conn.verified_at)}
        </span>
        <div className="ml-auto flex gap-2">
          <button onClick={() => act('verify', () => api('/facebook/connection/verify', { method: 'POST' }))}
            disabled={!!busy} className={btnGhost}>
            {busy === 'verify' ? 'Checking…' : 'Re-check'}
          </button>
          <button onClick={() => act('disconnect', () => api('/facebook/connection', { method: 'DELETE' }))}
            disabled={!!busy} className={`${btnGhost} text-red-600`}>
            Disconnect
          </button>
        </div>
      </div>

      {conn.status_detail && <p className="text-sm text-gray-500 mb-3">{conn.status_detail}</p>}
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      {conn.status === 'expired' ? (
        <CookieForm onConnected={onChange} submitLabel="Reconnect" />
      ) : (
        <div className="grid sm:grid-cols-2 gap-4 pt-3 border-t border-gray-100">
          <Toggle
            checked={conn.harvest_enabled}
            onChange={v => updateSetting('harvest_enabled', v)}
            label="Collect leads automatically"
            hint="Include this account in the scheduled agent runs (every 6 hours)."
          />
          <Toggle
            checked={conn.auto_join}
            onChange={v => updateSetting('auto_join', v)}
            label="Let the agent join groups"
            hint="Requests to join up to 2 highly relevant groups per run. Joining many groups quickly can get an account restricted."
          />
        </div>
      )}
    </section>
  )
}

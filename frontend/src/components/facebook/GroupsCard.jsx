import { useState } from 'react'
import { api, timeAgo, card, btnPrimary, btnGhost } from './api.js'

const MEMBERSHIP = {
  member:     { label: 'Member',      cls: 'bg-green-100 text-green-700' },
  pending:    { label: 'Requested',   cls: 'bg-amber-100 text-amber-700' },
  not_member: { label: 'Not a member', cls: 'bg-gray-100 text-gray-600' },
  unknown:    { label: 'Not checked', cls: 'bg-gray-100 text-gray-500' },
}

const TASK_SETS = [
  { tasks: ['discover'], label: 'Find new groups' },
  { tasks: ['harvest'], label: 'Collect leads' },
  { tasks: ['discover', 'join', 'harvest'], label: 'Run everything' },
]

function formatMembers(n) {
  if (!n) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return String(n)
}

function RunSummary({ conn }) {
  const run = conn.run
  if (run?.status === 'running') {
    return (
      <p className="text-sm text-blue-700 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-blue-600 animate-pulse" />
        Agent running ({run.tasks.join(', ')}) — started {timeAgo(run.started_at)}. This takes a few minutes.
      </p>
    )
  }
  const report = run?.report || conn.last_run_summary
  if (!report) return <p className="text-sm text-gray-400">The agent hasn't run yet.</p>
  return (
    <div className="text-sm text-gray-600">
      <p>
        Last run {timeAgo(report.finished_at || conn.last_run_at)}:{' '}
        {report.groups_added ?? 0} new groups, {report.leads_new ?? 0} new leads
        from {report.groups_harvested ?? 0} groups
        {report.joins_requested?.length ? `, asked to join ${report.joins_requested.length}` : ''}.
      </p>
      {report.errors?.length > 0 && (
        <ul className="mt-1 text-xs text-red-600 list-disc list-inside">
          {report.errors.slice(0, 3).map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
    </div>
  )
}

export default function GroupsCard({ conn, groups, onRunStarted, onGroupsChanged }) {
  const [url, setUrl] = useState('')
  const [areas, setAreas] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const running = conn.run?.status === 'running'
  const expired = conn.status === 'expired'

  async function run(tasks) {
    setError('')
    try {
      const areaList = areas.split(',').map(a => a.trim()).filter(Boolean)
      await api('/facebook/agent/run', { method: 'POST', body: { tasks, areas: areaList } })
      onRunStarted()
    } catch (err) {
      setError(err.message)
    }
  }

  async function addGroup(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('/facebook/groups', { method: 'POST', body: { url } })
      setUrl('')
      onGroupsChanged()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function toggle(group) {
    try {
      await api(`/facebook/groups/${group.id}`, { method: 'PATCH', body: { enabled: !group.enabled } })
      onGroupsChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className={card}>
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <h2 className="text-lg font-bold text-gray-900">Groups agent</h2>
        <span className="text-xs text-gray-400">{groups.length} groups tracked</span>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-3">
        {TASK_SETS.map(({ tasks, label }) => (
          <button key={label} onClick={() => run(tasks)} disabled={running || expired}
            className={tasks.length > 1 ? btnPrimary : btnGhost}>
            {label}
          </button>
        ))}
        <input value={areas} onChange={e => setAreas(e.target.value)}
          placeholder="Focus areas (optional): Baner, Wakad"
          className="flex-1 min-w-[200px] border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </div>
      {!conn.auto_join && (
        <p className="text-xs text-gray-400 mb-3">"Run everything" skips joining until you allow it above.</p>
      )}

      <div className="mb-4"><RunSummary conn={conn} /></div>
      {error && <p className="text-sm text-red-600 mb-3">{error}</p>}

      <form onSubmit={addGroup} className="flex gap-2 mb-4">
        <input value={url} onChange={e => setUrl(e.target.value)}
          placeholder="Add a group: https://www.facebook.com/groups/…"
          className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        <button type="submit" disabled={busy || !url.trim()} className={btnGhost}>Add</button>
      </form>

      {groups.length === 0 ? (
        <p className="text-sm text-gray-400">No groups yet. "Find new groups" searches Facebook; "Collect leads" starts with a built-in list of Pune rental groups.</p>
      ) : (
        <div className="overflow-x-auto -mx-5">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                <th className="px-5 py-2 font-medium">Group</th>
                <th className="px-2 py-2 font-medium">Members</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Leads</th>
                <th className="px-2 py-2 font-medium">Last read</th>
                <th className="px-5 py-2 font-medium text-right">Read</th>
              </tr>
            </thead>
            <tbody>
              {groups.map(g => {
                const m = MEMBERSHIP[g.membership] || MEMBERSHIP.unknown
                return (
                  <tr key={g.id} className={`border-b border-gray-50 ${g.enabled ? '' : 'opacity-50'}`}>
                    <td className="px-5 py-2">
                      <a href={g.url} target="_blank" rel="noreferrer"
                        className="font-medium text-gray-800 hover:text-blue-600">{g.name || g.group_key}</a>
                      <span className="block text-xs text-gray-400">
                        {g.privacy || 'privacy unknown'} · relevance {Number(g.relevance || 0).toFixed(1)} · {g.added_by}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-gray-600">{formatMembers(g.member_count)}</td>
                    <td className="px-2 py-2">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${m.cls}`}>{m.label}</span>
                    </td>
                    <td className="px-2 py-2 text-gray-600">{g.leads_found || 0}</td>
                    <td className="px-2 py-2 text-gray-500 text-xs">{timeAgo(g.last_harvested_at)}</td>
                    <td className="px-5 py-2 text-right">
                      <input type="checkbox" checked={g.enabled} onChange={() => toggle(g)}
                        className="w-4 h-4 accent-blue-600" title="Read this group for leads" />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

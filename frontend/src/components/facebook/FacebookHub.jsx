import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import ConnectCard from './ConnectCard.jsx'
import GroupsCard from './GroupsCard.jsx'
import LeadsCard from './LeadsCard.jsx'

export default function FacebookHub() {
  const [conn, setConn] = useState(null)
  const [groups, setGroups] = useState([])
  const [error, setError] = useState('')
  const [leadsKey, setLeadsKey] = useState(0)
  const wasRunning = useRef(false)

  const loadConnection = useCallback(async () => {
    try {
      setConn(await api('/facebook/connection'))
      setError('')
    } catch (err) {
      setError(err.message)
    }
  }, [])

  const loadGroups = useCallback(async () => {
    try {
      setGroups((await api('/facebook/groups')).groups)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => { loadConnection() }, [loadConnection])
  useEffect(() => { if (conn?.connected) loadGroups() }, [conn?.connected, loadGroups])

  const running = conn?.run?.status === 'running'
  useEffect(() => {
    if (!running) return
    const timer = setInterval(loadConnection, 5000)
    return () => clearInterval(timer)
  }, [running, loadConnection])

  useEffect(() => {
    if (wasRunning.current && !running) {
      loadGroups()
      setLeadsKey(k => k + 1)
    }
    wasRunning.current = running
  }, [running, loadGroups])

  if (!conn) {
    return error
      ? <p className="text-sm text-red-600">{error}</p>
      : <p className="text-sm text-gray-400 animate-pulse">Loading…</p>
  }

  return (
    <div className="space-y-6">
      <ConnectCard conn={conn} onChange={setConn} />
      {conn.connected && (
        <>
          <GroupsCard conn={conn} groups={groups} onRunStarted={loadConnection} onGroupsChanged={loadGroups} />
          <LeadsCard refreshKey={leadsKey} />
        </>
      )}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  )
}

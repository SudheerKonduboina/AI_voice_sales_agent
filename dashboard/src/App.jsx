import { useCallback, useEffect, useState } from 'react'

const API = ''

async function fetchJson(path) {
  const res = await fetch(`${API}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

/* ── Reusable Components ─────────────────────────────────── */

function StatCard({ label, value, sub }) {
  return (
    <div className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-4 transition-colors">
      <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
      <p className="text-2xl font-semibold mt-1 text-gray-900 dark:text-gray-100">{value}</p>
      {sub && <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">{sub}</p>}
    </div>
  )
}

function StatusBadge({ status }) {
  const colors = {
    Booked: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
    Pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300',
    'Not Interested': 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
    'No Answer': 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400',
    Called: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  }
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${colors[status] || colors.Pending}`}>
      {status || 'Pending'}
    </span>
  )
}

function EmptyState({ message }) {
  return (
    <tr><td colSpan={99} className="p-8 text-center text-gray-400 dark:text-gray-500">{message}</td></tr>
  )
}

/* ── Icons (inline SVG to avoid dependencies) ────────────── */

function SunIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path d="M10 2a.75.75 0 01.75.75v1.5a.75.75 0 01-1.5 0v-1.5A.75.75 0 0110 2zm0 13a.75.75 0 01.75.75v1.5a.75.75 0 01-1.5 0v-1.5A.75.75 0 0110 15zm8-5a.75.75 0 01-.75.75h-1.5a.75.75 0 010-1.5h1.5A.75.75 0 0118 10zM5 10a.75.75 0 01-.75.75h-1.5a.75.75 0 010-1.5h1.5A.75.75 0 015 10zm11.95-4.95a.75.75 0 010 1.06l-1.06 1.06a.75.75 0 01-1.06-1.06l1.06-1.06a.75.75 0 011.06 0zm-12.73 9.73a.75.75 0 010 1.06l-1.06 1.06a.75.75 0 01-1.06-1.06l1.06-1.06a.75.75 0 011.06 0zM16.95 15.95a.75.75 0 01-1.06 0l-1.06-1.06a.75.75 0 011.06-1.06l1.06 1.06a.75.75 0 010 1.06zm-12.73-9.73a.75.75 0 01-1.06 0L2.1 5.16a.75.75 0 011.06-1.06l1.06 1.06a.75.75 0 010 1.06zM10 7a3 3 0 100 6 3 3 0 000-6z" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path fillRule="evenodd" d="M7.455 2.004a.75.75 0 01.26.77 7 7 0 009.958 7.957.75.75 0 011.067.853A8.5 8.5 0 1118.75 3.5a.75.75 0 01-.297.504 7.032 7.032 0 01-1.498-.001.75.75 0 01-.51-.26A8.467 8.467 0 007.455 2.004z" clipRule="evenodd" />
    </svg>
  )
}

/* ── Main Application ────────────────────────────────────── */

export default function App() {
  const [tab, setTab] = useState('dashboard')
  const [dark, setDark] = useState(() => {
    const stored = localStorage.getItem('theme')
    if (stored) return stored === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })
  const [leads, setLeads] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [calls, setCalls] = useState([])
  const [logs, setLogs] = useState([])
  const [meetings, setMeetings] = useState([])
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedLead, setSelectedLead] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Theme persistence
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (search) params.set('search', search)
      if (statusFilter) params.set('status', statusFilter)
      const [leadsData, analyticsData, callsData, logsData, meetingsData] = await Promise.all([
        fetchJson(`/api/leads?${params}`),
        fetchJson('/api/analytics'),
        fetchJson('/api/analytics/calls'),
        fetchJson('/api/logs?lines=100'),
        fetchJson('/api/meetings'),
      ])
      setLeads(leadsData.leads || [])
      setAnalytics(analyticsData)
      setCalls(callsData.calls || [])
      setLogs(logsData.lines || [])
      setMeetings(meetingsData.meetings || [])
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }, [search, statusFilter])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 15000)
    return () => clearInterval(id)
  }, [refresh])

  const runCall = useCallback(async (leadId) => {
    setLoading(true)
    try {
      await fetch(`${API}/api/call`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lead_id: leadId, mode: 'simulate' }),
      })
      await refresh()
    } catch (e) {
      setError(String(e.message || e))
    } finally {
      setLoading(false)
    }
  }, [refresh])

  const selectLead = async (lead) => {
    setSelectedLead(lead)
    try {
      const data = await fetchJson(`/api/transcript/${lead.lead_id}`)
      setSelectedLead(prev => prev && prev.lead_id === lead.lead_id ? { ...prev, ...data } : prev)
    } catch {
      setError('Failed to load transcript data')
    }
  }

  const exportData = async () => {
    try {
      const res = await fetch(`${API}/api/export`)
      if (!res.ok) throw new Error(`Export failed: ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `sales-agent-export-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(String(e.message || e))
    }
  }

  const getLogLineColor = (line) => {
    if (line.includes('ERROR') || line.includes('CRITICAL')) return 'text-red-500 dark:text-red-400'
    if (line.includes('WARNING') || line.includes('WARN')) return 'text-yellow-600 dark:text-yellow-400'
    if (line.includes('INFO')) return 'text-green-600 dark:text-green-400/90'
    if (line.includes('DEBUG')) return 'text-gray-400 dark:text-gray-500'
    return 'text-gray-700 dark:text-gray-300'
  }

  const tabs = [
    ['dashboard', '📊 Dashboard'],
    ['leads', '👥 Leads'],
    ['meetings', '📅 Meetings'],
    ['callHistory', '📞 Call History'],
    ['analytics', '📈 Analytics'],
    ['logs', '📋 Live Logs'],
  ]

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 transition-colors">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="border-b border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-900/80 backdrop-blur sticky top-0 z-10 transition-colors">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">AI Voice Sales Agent</h1>
          <div className="flex items-center gap-2">
            <button
              id="btn-export"
              onClick={exportData}
              className="text-sm px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors"
              title="Export data"
            >
              Export
            </button>
            <button
              id="btn-theme-toggle"
              onClick={() => setDark(!dark)}
              className="p-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition-colors"
              aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
              title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {dark ? <SunIcon /> : <MoonIcon />}
            </button>
            <button
              id="btn-refresh"
              onClick={refresh}
              disabled={loading}
              className="text-sm px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 transition-colors"
            >
              {loading ? 'Loading…' : 'Refresh'}
            </button>
          </div>
        </div>
        <nav className="max-w-7xl mx-auto px-4 flex gap-1 pb-2" role="tablist">
          {tabs.map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                tab === id
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      {/* ── Main Content ───────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {error && (
          <div id="error-banner" className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/40 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-200 text-sm flex justify-between items-center">
            <span>{error}</span>
            <button onClick={() => setError('')} className="ml-3 text-red-500 hover:text-red-700 dark:hover:text-red-300" aria-label="Dismiss error">&times;</button>
          </div>
        )}

        {/* ── Dashboard Tab ──────────────────────────────── */}
        {tab === 'dashboard' && analytics && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <StatCard label="Total Calls" value={analytics.total_calls ?? 0} />
              <StatCard label="Successful" value={analytics.successful_calls ?? 0} />
              <StatCard label="Success Rate" value={`${analytics.success_rate_pct ?? 0}%`} />
              <StatCard label="Meetings Booked" value={analytics.booked_meetings ?? 0} />
              <StatCard label="Qualification Rate" value={`${analytics.qualification_rate_pct ?? 0}%`} />
              <StatCard label="Avg Duration" value={`${analytics.average_duration_seconds ?? 0}s`} />
              <StatCard label="Avg Response" value={`${analytics.average_response_time_ms ?? 0}ms`} />
              <StatCard
                label="Total Tokens"
                value={(analytics.total_prompt_tokens ?? 0) + (analytics.total_completion_tokens ?? 0)}
                sub={`${analytics.total_prompt_tokens ?? 0} prompt / ${analytics.total_completion_tokens ?? 0} completion`}
              />
            </div>

            <section>
              <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">Recent Calls</h2>
              <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden bg-white dark:bg-gray-900/20 transition-colors">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500 dark:text-gray-400">
                    <tr>
                      <th className="text-left p-3">Lead</th>
                      <th className="text-left p-3">Status</th>
                      <th className="text-left p-3">Qualification</th>
                      <th className="text-left p-3">Duration</th>
                      <th className="text-left p-3">Tokens</th>
                      <th className="text-left p-3">Meeting</th>
                    </tr>
                  </thead>
                  <tbody>
                    {calls.slice(-10).reverse().map((c, i) => (
                      <tr key={i} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors">
                        <td className="p-3 font-medium">{c.lead_name || c.lead_id}</td>
                        <td className="p-3"><StatusBadge status={c.status} /></td>
                        <td className="p-3">{c.qualification}</td>
                        <td className="p-3">{c.duration_seconds}s</td>
                        <td className="p-3 font-mono text-xs">{c.prompt_tokens + c.completion_tokens}</td>
                        <td className="p-3">{c.meeting_booked ? '✅' : '—'}</td>
                      </tr>
                    ))}
                    {!calls.length && <EmptyState message="No calls recorded yet" />}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}

        {/* ── Leads Tab ──────────────────────────────────── */}
        {tab === 'leads' && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <input
                id="input-search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search leads…"
                className="px-3 py-2 rounded-lg bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-700 text-sm flex-1 min-w-[200px] text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              />
              <select
                id="select-status-filter"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-2 rounded-lg bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors"
              >
                <option value="">All statuses</option>
                {['Pending', 'Booked', 'Called', 'Not Interested', 'No Answer'].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden bg-white dark:bg-gray-900/20 transition-colors">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500 dark:text-gray-400">
                    <tr>
                      <th className="text-left p-3">ID</th>
                      <th className="text-left p-3">Name</th>
                      <th className="text-left p-3">Status</th>
                      <th className="text-left p-3">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leads.map((l) => (
                      <tr
                        key={l.lead_id}
                        className={`border-t border-gray-100 dark:border-gray-800 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors ${
                          selectedLead?.lead_id === l.lead_id ? 'bg-blue-50 dark:bg-gray-900' : ''
                        }`}
                        onClick={() => selectLead(l)}
                        tabIndex={0}
                        onKeyDown={(e) => e.key === 'Enter' && selectLead(l)}
                      >
                        <td className="p-3 font-semibold">{l.lead_id}</td>
                        <td className="p-3">{l.name}</td>
                        <td className="p-3"><StatusBadge status={l.status} /></td>
                        <td className="p-3">
                          {(l.status === 'Pending' || !l.status) && (
                            <button
                              onClick={(e) => { e.stopPropagation(); runCall(l.lead_id) }}
                              className="text-xs px-2.5 py-1 rounded bg-green-600 hover:bg-green-500 text-white transition-colors focus:outline-none focus:ring-2 focus:ring-green-400"
                            >
                              Call
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {!leads.length && <EmptyState message="No leads match filters" />}
                  </tbody>
                </table>
              </div>

              {selectedLead && (
                <div className="rounded-xl border border-gray-200 dark:border-gray-800 p-4 space-y-3 text-sm bg-white dark:bg-gray-900/10 transition-colors">
                  <div className="flex justify-between items-start">
                    <h3 className="font-semibold text-base">{selectedLead.name}</h3>
                    <button onClick={() => setSelectedLead(null)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" aria-label="Close details">&times;</button>
                  </div>
                  <p className="text-gray-500 dark:text-gray-400">{selectedLead.phone} · {selectedLead.email}</p>
                  <hr className="border-gray-200 dark:border-gray-800" />
                  <div><span className="text-gray-500 font-medium">Status:</span> <StatusBadge status={selectedLead.status} /></div>
                  <div><span className="text-gray-500 font-medium">Qualification:</span> {selectedLead.qualification || '—'}</div>
                  <div><span className="text-gray-500 font-medium">Meeting:</span> {selectedLead.meeting_datetime || '—'}</div>
                  <div><span className="text-gray-500 font-medium">Follow-up:</span> {selectedLead.follow_up_date || '—'}</div>
                  <div>
                    <span className="text-gray-500 font-medium">Summary:</span>
                    <p className="mt-1 text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/40 p-2.5 rounded-lg border border-gray-200 dark:border-gray-800">{selectedLead.conversation_summary || '—'}</p>
                  </div>
                  <div>
                    <span className="text-gray-500 font-medium">Requirements:</span>
                    <p className="mt-1 text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/40 p-2.5 rounded-lg border border-gray-200 dark:border-gray-800">{selectedLead.customer_requirements || '—'}</p>
                  </div>
                  <div>
                    <span className="text-gray-500 font-medium">Objections:</span>
                    <p className="mt-1 text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/40 p-2.5 rounded-lg border border-gray-200 dark:border-gray-800">{selectedLead.objections_raised || '—'}</p>
                  </div>
                  <div>
                    <span className="text-gray-500 font-medium">Notes:</span>
                    <p className="mt-1 text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/40 p-2.5 rounded-lg border border-gray-200 dark:border-gray-800">{selectedLead.notes || '—'}</p>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Meetings Tab ───────────────────────────────── */}
        {tab === 'meetings' && (
          <div className="space-y-4">
            <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400">Booked Meetings</h2>
            <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden bg-white dark:bg-gray-900/20 transition-colors">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500 dark:text-gray-400">
                  <tr>
                    <th className="text-left p-3">Lead ID</th>
                    <th className="text-left p-3">Contact Name</th>
                    <th className="text-left p-3">Phone</th>
                    <th className="text-left p-3">Meeting Time</th>
                    <th className="text-left p-3">Status</th>
                    <th className="text-left p-3">Qualification</th>
                  </tr>
                </thead>
                <tbody>
                  {meetings.map((m, i) => (
                    <tr key={i} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors">
                      <td className="p-3 font-semibold">{m.lead_id}</td>
                      <td className="p-3 font-medium">{m.name}</td>
                      <td className="p-3">{m.phone}</td>
                      <td className="p-3 text-blue-600 dark:text-blue-400 font-semibold">{m.meeting_datetime}</td>
                      <td className="p-3"><StatusBadge status={m.status} /></td>
                      <td className="p-3">{m.qualification}</td>
                    </tr>
                  ))}
                  {!meetings.length && <EmptyState message="No meetings booked yet" />}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Call History Tab ────────────────────────────── */}
        {tab === 'callHistory' && (
          <div className="space-y-4">
            <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400">Complete Call History</h2>
            <div className="rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden bg-white dark:bg-gray-900/20 transition-colors">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500 dark:text-gray-400">
                  <tr>
                    <th className="text-left p-3">Time</th>
                    <th className="text-left p-3">Lead</th>
                    <th className="text-left p-3">Status</th>
                    <th className="text-left p-3">Qualification</th>
                    <th className="text-left p-3">Duration</th>
                    <th className="text-left p-3">Inference</th>
                    <th className="text-left p-3">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {calls.slice().reverse().map((c, i) => (
                    <tr key={i} className="border-t border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-900/50 transition-colors">
                      <td className="p-3 text-gray-400 text-xs">{new Date(c.timestamp).toLocaleString()}</td>
                      <td className="p-3 font-medium">{c.lead_name || c.lead_id}</td>
                      <td className="p-3"><StatusBadge status={c.status} /></td>
                      <td className="p-3">{c.qualification}</td>
                      <td className="p-3">{c.duration_seconds}s</td>
                      <td className="p-3">{c.inference_time_seconds}s</td>
                      <td className="p-3 font-mono text-xs">{c.prompt_tokens + c.completion_tokens} ({c.prompt_tokens}p / {c.completion_tokens}c)</td>
                    </tr>
                  ))}
                  {!calls.length && <EmptyState message="No calls in history" />}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Analytics Tab ──────────────────────────────── */}
        {tab === 'analytics' && analytics && (
          <div className="space-y-4">
            <pre className="rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-4 text-xs overflow-auto text-gray-800 dark:text-gray-200 transition-colors">
              {JSON.stringify(analytics, null, 2)}
            </pre>
            {analytics.qualifications && (
              <div className="rounded-xl border border-gray-200 dark:border-gray-800 p-4 bg-white dark:bg-gray-900/10 transition-colors">
                <h3 className="text-sm font-medium mb-2">Qualifications Breakdown</h3>
                {Object.entries(analytics.qualifications).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm py-1 border-b border-gray-100 dark:border-gray-800">
                    <span className="font-medium">{k}</span><span>{v}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Live Logs Tab ──────────────────────────────── */}
        {tab === 'logs' && (
          <div className="rounded-xl bg-white dark:bg-black border border-gray-200 dark:border-gray-800 p-4 font-mono text-xs h-[70vh] overflow-auto transition-colors">
            {logs.map((line, i) => (
              <div key={i} className={`${getLogLineColor(line)} whitespace-pre-wrap py-0.5`}>{line}</div>
            ))}
            {!logs.length && <p className="text-gray-400 dark:text-gray-500">No logs yet</p>}
          </div>
        )}
      </main>
    </div>
  )
}

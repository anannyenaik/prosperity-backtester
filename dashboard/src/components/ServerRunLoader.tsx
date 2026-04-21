import { useState } from 'react'
import { RefreshCw, Server } from 'lucide-react'
import { clsx } from 'clsx'
import { useStore, type ServerRunMeta } from '../store'
import type { DashboardPayload } from '../types'
import { fmtBytes, fmtDate, fmtNum } from '../lib/format'

export function ServerRunLoader() {
  const { serverRuns, setServerRuns, loadRun } = useStore()
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)

  async function fetchRuns(): Promise<ServerRunMeta[]> {
    setLoading(true)
    try {
      const res = await fetch('/api/runs')
      if (res.ok) {
        const data = await res.json()
        const runs = data as ServerRunMeta[]
        setServerRuns(runs)
        setOpen(true)
        return runs
      }
    } catch {
      setOpen(true)
    } finally {
      setLoading(false)
    }
    return []
  }

  async function loadFromServer(run: ServerRunMeta) {
    const res = await fetch(`/api/run/${encodeURIComponent(run.path)}`)
    if (res.ok) {
      const payload = (await res.json()) as DashboardPayload
      loadRun(payload, run.name)
    }
  }

  async function loadLatestFromServer() {
    const runs = await fetchRuns()
    if (runs.length > 0) {
      await loadFromServer(runs[0])
    }
  }

  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={loadLatestFromServer}
          disabled={loading}
          className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
        >
          {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
          Open latest run
        </button>
        <button
          onClick={() => void fetchRuns()}
          disabled={loading}
          className="subtle-button inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs"
        >
          {loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Server className="h-3.5 w-3.5" />}
          Browse local server
        </button>
      </div>

      {open && serverRuns.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-lg border border-border bg-bg/45">
          <div className="hud-label border-b border-border bg-white/[0.03] px-4 py-3 text-muted">
            Available bundles ({serverRuns.length})
          </div>
          <div className="max-h-72 overflow-y-auto divide-y divide-border">
            {serverRuns.map((run) => (
              <button
                key={run.path}
                onClick={() => loadFromServer(run)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-accent/5"
              >
                <span className="min-w-0">
                  <span className="block truncate font-display text-xs font-semibold uppercase tracking-[0.08em] text-txt">
                    {run.name}
                  </span>
                  <span className="hud-label mt-1 flex flex-wrap gap-2 text-muted">
                    <span>{run.type}</span>
                    {run.profile && <span>{run.profile}</span>}
                    {run.sizeBytes != null && <span>{fmtBytes(run.sizeBytes)}</span>}
                    <span>{fmtDate(run.createdAt)}</span>
                  </span>
                  <span className="mt-1 block truncate text-[11px] text-muted/85">{run.path}</span>
                </span>
                {run.finalPnl != null && (
                  <span className={clsx('font-mono text-xs', run.finalPnl >= 0 ? 'text-good' : 'text-bad')}>
                    {fmtNum(run.finalPnl)}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {open && serverRuns.length === 0 && (
        <div className="mt-3 rounded-lg border border-border bg-white/[0.025] px-4 py-3 text-sm text-muted">
          No dashboard bundles were found under the served directory.
        </div>
      )}
    </div>
  )
}

import { clsx } from 'clsx'
import type { DashboardPayload } from '../types'
import { interpretBundle } from '../lib/bundles'

interface Props {
  payload: DashboardPayload
  className?: string
}

export function BundleBadge({ payload, className }: Props) {
  const bundle = interpretBundle(payload)
  const profile = payload.meta?.outputProfile?.profile
  const workflowTier = payload.meta?.provenance?.workflow_tier
  const backend = payload.meta?.provenance?.runtime?.engine_backend
  const mcBackend = payload.meta?.provenance?.runtime?.monte_carlo_backend

  return (
    <div className={clsx('inline-flex flex-wrap items-center gap-2', className)}>
      <span className="hud-label rounded-lg border border-accent/25 bg-accent/10 px-3 py-2 text-accent">
        {bundle.badge}
      </span>
      {profile && (
        <span
          className={clsx(
            'hud-label rounded-lg px-3 py-2',
            profile === 'full'
              ? 'border border-warn/25 bg-warn/10 text-warn'
              : 'border border-good/25 bg-good/10 text-good',
          )}
        >
          {profile} profile
        </span>
      )}
      {workflowTier && (
        <span className="hud-label rounded-lg border border-border bg-white/[0.025] px-3 py-2 text-muted">
          {workflowTier}
        </span>
      )}
      {backend && (
        <span className={engineBadgeClass(backend)} title="Engine backend that executed the trader callback">
          {backend}
        </span>
      )}
      {mcBackend && (
        <span className={mcBadgeClass(mcBackend)} title="Monte Carlo execution backend">
          mc: {mcBackend}
        </span>
      )}
      {bundle.rawType !== bundle.type && (
        <span className="hud-label rounded-lg border border-border bg-white/[0.025] px-3 py-2 text-muted">
          raw: {bundle.rawType}
        </span>
      )}
    </div>
  )
}

function engineBadgeClass(backend: string): string {
  // Engine backends: "python" (default replay engine) and "rust" (subprocess
  // worker for the Rust MC pipeline).  Tint rust gold so the backend choice is
  // legible at a glance — it is a meaningful trust + perf signal.
  const base = 'hud-label rounded-lg px-3 py-2'
  if (backend === 'rust') return `${base} border border-warn/30 bg-warn/10 text-warn`
  return `${base} border border-border bg-white/[0.025] text-muted`
}

function mcBadgeClass(mcBackend: string): string {
  const base = 'hud-label rounded-lg px-3 py-2'
  if (mcBackend === 'rust') return `${base} border border-warn/30 bg-warn/10 text-warn`
  if (mcBackend === 'streaming') return `${base} border border-accent/30 bg-accent/10 text-accent`
  if (mcBackend === 'classic') return `${base} border border-border bg-white/[0.04] text-txt-soft`
  return `${base} border border-border bg-white/[0.025] text-muted`
}

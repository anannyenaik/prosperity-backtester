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
        <span className="hud-label rounded-lg border border-border bg-white/[0.025] px-3 py-2 text-muted">
          {backend}
        </span>
      )}
      {mcBackend && (
        <span className="hud-label rounded-lg border border-border bg-white/[0.025] px-3 py-2 text-muted">
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

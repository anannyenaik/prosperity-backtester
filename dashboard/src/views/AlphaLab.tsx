import { useMemo } from 'react'
import { FlaskConical, ShieldAlert } from 'lucide-react'
import { useStore } from '../store'
import { Card } from '../components/Card'
import { DataTable, type ColDef } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { MetricCard } from '../components/MetricCard'
import { PageHeader } from '../components/PageHeader'
import { BundleBadge } from '../components/BundleBadge'
import { fmtInt, fmtNum, fmtPct } from '../lib/format'
import {
  ALPHA_ACTION_LABELS,
  ALPHA_BUCKET_LABELS,
  ALPHA_CLASS_LABELS,
  buildAlphaLabData,
  type AlphaBucket,
  type AlphaEvidence,
  type AlphaHypothesis,
  type AlphaMetric,
  type AlphaTone,
  type ConditionalRow,
  type MafEvidenceRow,
  type NextTestRow,
  type RobustnessRow,
} from '../lib/alpha'

const BUCKET_ORDER: AlphaBucket[] = ['strong', 'testing', 'active', 'website', 'rejected']

const toneText: Record<AlphaTone, string> = {
  good: 'text-good',
  bad: 'text-bad',
  warn: 'text-warn',
  neutral: 'text-txt-soft',
  accent: 'text-accent',
}

const classBadge: Record<AlphaHypothesis['classification'], string> = {
  public_data: 'border-good/30 bg-good/10 text-good',
  local_bt: 'border-accent/30 bg-accent/10 text-accent',
  website_only: 'border-warn/35 bg-warn/10 text-warn',
  weak_rejected: 'border-border bg-white/[0.035] text-muted',
}

export function AlphaLab() {
  const { getActiveRun, getCompareRun } = useStore()
  const run = getActiveRun()
  const compareRun = getCompareRun()

  const data = useMemo(
    () => (run ? buildAlphaLabData(run.payload, compareRun?.payload) : null),
    [run, compareRun],
  )

  if (!run || !data) {
    return (
      <EmptyState
        icon={<FlaskConical className="h-10 w-10" />}
        title="No run loaded"
        message="Load a dashboard bundle to build the Alpha Lab evidence registry."
      />
    )
  }

  const strongCount = data.hypotheses.filter((item) => item.bucket === 'strong').length
  const websiteCount = data.hypotheses.filter((item) => item.classification === 'website_only').length
  const rejectedCount = data.hypotheses.filter((item) => item.classification === 'weak_rejected').length
  const top = data.topCandidates[0]

  return (
    <div className="space-y-5">
      <PageHeader
        kicker="Alpha Lab / evidence engine"
        title="Hypotheses"
        accent="prioritised"
        description="A bundle-aware registry for candidate edge patterns, falsification evidence, classification boundaries and the next tests worth running."
        meta={<BundleBadge payload={run.payload} />}
      />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Hypotheses" value={fmtInt(data.hypotheses.length)} sub={data.generatedFrom.join(' / ')} />
        <MetricCard label="Strong evidence" value={fmtInt(strongCount)} tone={strongCount > 0 ? 'good' : 'neutral'} sub="Meets support and priority gates" />
        <MetricCard label="Website-only" value={fmtInt(websiteCount)} tone={websiteCount > 0 ? 'warn' : 'neutral'} sub="Unresolved MAF or access dependency" />
        <MetricCard label="Top priority" value={top ? `${top.priorityLabel} ${Math.round(top.priorityScore)}` : '-'} tone={top ? toneForPriority(top.priorityLabel) : 'neutral'} sub={top?.name ?? 'No promoted candidate'} />
      </div>

      <Card title="Alpha overview board" subtitle="Ranked by evidence score, with classifications kept explicit. Weak ideas remain visible so they can be rejected deliberately.">
        {data.topCandidates.length > 0 ? (
          <DataTable rows={data.topCandidates} cols={candidateCols} maxRows={10} striped />
        ) : (
          <EmptyState title="No promoted candidates" message="This bundle does not contain enough evidence to promote a candidate edge." />
        )}
      </Card>

      <Card title="Evidence classes" subtitle="The registry separates public signals, local backtester capture, website-only uncertainty and rejected ideas.">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          {([
            ['Public-data edge', 'Uses public CSV or derived book/fair diagnostics only. It still needs backtesting.'],
            ['Local-BT edge', 'Depends on replay, fills, markouts, MC or comparison assumptions.'],
            ['Website-only edge', 'Needs website feedback because MAF or hidden access mechanics decide it.'],
            ['Weak / rejected', 'Insufficient, adverse or too noisy for implementation work.'],
          ] as const).map(([label, detail]) => (
            <div key={label} className="rounded-lg border border-border bg-white/[0.025] p-4">
              <div className="hud-label text-accent">{label}</div>
              <p className="mt-3 text-xs leading-5 text-muted">{detail}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Hypothesis registry" subtitle="Buckets are assigned from evidence class, confidence, priority and the required next action.">
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-5">
          {BUCKET_ORDER.map((bucket) => (
            <div key={bucket} className="min-w-0 rounded-lg border border-border bg-bg/30 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="hud-label text-accent">{ALPHA_BUCKET_LABELS[bucket]}</div>
                <span className="font-mono text-xs text-muted">{fmtInt(data.buckets[bucket].length)}</span>
              </div>
              <div className="space-y-3">
                {data.buckets[bucket].slice(0, 6).map((item) => (
                  <HypothesisLine key={item.id} item={item} />
                ))}
                {data.buckets[bucket].length === 0 && (
                  <div className="text-xs leading-5 text-muted">No hypotheses in this bucket for the loaded bundle.</div>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Evidence explorer" subtitle="Each promoted hypothesis includes support and falsification evidence. Missing support stays explicit.">
        {data.hypotheses.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {data.hypotheses.slice(0, 8).map((item) => (
              <EvidencePanel key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <EmptyState title="No hypotheses built" message="The loaded bundle has no supported evidence sections for Alpha Lab." />
        )}
      </Card>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        {data.productPanels.map((panel) => (
          <Card
            key={panel.product}
            title={`${panel.label} alpha panel`}
            subtitle={panel.product === 'ASH_COATED_OSMIUM'
              ? 'Residuals, imbalance proxy, quote quality, recycle diagnostics and one-sided state checks.'
              : 'Time-fair residuals, continuation evidence, cap usage, aggressive fills and monetisation timing.'}
          >
            <ProductPanel panel={panel} />
          </Card>
        ))}
      </div>

      <Card title="MAF / website-only alpha panel" subtitle="Scenario dependence, access sensitivity and unresolved website-only questions.">
        <MetricGrid metrics={data.mafPanel.metrics} />
        {data.mafPanel.rows.length > 0 ? (
          <div className="mt-5">
            <DataTable rows={data.mafPanel.rows} cols={mafCols} maxRows={16} striped />
          </div>
        ) : (
          <EmptyState className="mt-3" title="No MAF scenario rows" message={data.mafPanel.message} />
        )}
        <div className="mt-4 flex items-start gap-3 rounded-lg border border-warn/25 bg-warn/10 p-4 text-xs leading-5 text-warn">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{data.mafPanel.message}</span>
        </div>
      </Card>

      <Card title="Robustness board" subtitle="Cross-day stability, MC support, scenario stability and registry health.">
        <DataTable rows={data.robustnessRows} cols={robustnessCols} maxRows={12} striped />
      </Card>

      <Card title="Next-test queue" subtitle="Actions are generated from evidence and exploitability, not from raw metric novelty.">
        {data.nextTests.length > 0 ? (
          <DataTable rows={data.nextTests} cols={nextTestCols} maxRows={10} striped />
        ) : (
          <EmptyState title="No next tests" message="All ideas are missing, weak or waiting for more evidence." />
        )}
      </Card>

      {(data.missingMessages.length > 0 || rejectedCount > 0) && (
        <Card title="Missing and rejected evidence" subtitle="The lab should fail closed when evidence is absent.">
          <div className="space-y-3 text-sm leading-6 text-muted">
            {data.missingMessages.map((message) => (
              <div key={message} className="rounded-lg border border-border bg-white/[0.02] px-4 py-3">{message}</div>
            ))}
            {rejectedCount > 0 && (
              <div className="rounded-lg border border-border bg-white/[0.02] px-4 py-3">
                {fmtInt(rejectedCount)} weak or rejected hypotheses are retained in the registry to avoid quietly recycling noisy ideas.
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}

const candidateCols: ColDef<AlphaHypothesis>[] = [
  { key: 'priorityScore', header: 'Priority', fmt: 'int', render: (_v, row) => `${row.priorityLabel} ${Math.round(row.priorityScore)}`, tone: (_v, row) => priorityTone(row.priorityLabel) },
  { key: 'name', header: 'Hypothesis', fmt: 'str' },
  { key: 'product', header: 'Product', fmt: 'str' },
  { key: 'classification', header: 'Class', render: (_v, row) => <ClassBadge item={row} />, sortable: false },
  { key: 'confidence', header: 'Confidence', render: (_v, row) => fmtPct(row.confidence), tone: (_v, row) => confidenceTone(row.confidence) },
  { key: 'sampleSize', header: 'Support', render: (_v, row) => (row.sampleSize == null ? '-' : fmtInt(row.sampleSize)), align: 'right' },
  { key: 'currentCapture', header: 'Capture estimate', fmt: 'str' },
  { key: 'nextAction', header: 'Next action', render: (_v, row) => ALPHA_ACTION_LABELS[row.nextAction] },
]

const conditionCols: ColDef<ConditionalRow>[] = [
  { key: 'state', header: 'State', fmt: 'str' },
  { key: 'support', header: 'Rows', fmt: 'int', align: 'right' },
  { key: 'mean_residual', header: 'Mean residual', fmt: 'num', align: 'right' },
  { key: 'next_1_mean', header: 'Next +1', fmt: 'num', align: 'right' },
  { key: 'next_5_mean', header: 'Next +5', fmt: 'num', align: 'right' },
  { key: 'hit_rate_5', header: 'Hit +5', fmt: 'pct', align: 'right' },
]

const mafCols: ColDef<MafEvidenceRow>[] = [
  { key: 'scenario', header: 'Scenario', fmt: 'str' },
  { key: 'trader', header: 'Trader', fmt: 'str' },
  { key: 'classification', header: 'Class', fmt: 'str' },
  { key: 'final_pnl', header: 'Final PnL', fmt: 'num', tone: (value) => valueTone(Number(value)) },
  { key: 'access_edge', header: 'Access edge', fmt: 'num', tone: (value) => valueTone(Number(value)) },
  { key: 'break_even_maf', header: 'Break-even MAF', fmt: 'num', tone: (value) => valueTone(Number(value)) },
  { key: 'mc_mean', header: 'MC mean', fmt: 'num', tone: (value) => valueTone(Number(value)) },
  { key: 'mc_p05', header: 'MC P05', fmt: 'num', tone: (value) => valueTone(Number(value)) },
]

const robustnessCols: ColDef<RobustnessRow>[] = [
  { key: 'source', header: 'Source', fmt: 'str' },
  { key: 'classification', header: 'Class', fmt: 'str' },
  { key: 'support', header: 'Support', fmt: 'str' },
  { key: 'against', header: 'Against', fmt: 'str' },
  { key: 'action', header: 'Action', fmt: 'str' },
]

const nextTestCols: ColDef<NextTestRow>[] = [
  { key: 'rank', header: '#', fmt: 'int', width: 56 },
  { key: 'action', header: 'Action', fmt: 'str' },
  { key: 'hypothesis', header: 'Hypothesis', fmt: 'str' },
  { key: 'classification', header: 'Class', fmt: 'str' },
  { key: 'reason', header: 'Reason', fmt: 'str' },
  { key: 'priority', header: 'Priority', fmt: 'str' },
]

function ProductPanel({ panel }: { panel: ReturnType<typeof buildAlphaLabData>['productPanels'][number] }) {
  return (
    <div className="space-y-5">
      <MetricGrid metrics={panel.metrics} />
      {panel.conditionRows.length > 0 ? (
        <div>
          <div className="hud-label mb-3 text-accent">Conditional return table</div>
          <DataTable rows={panel.conditionRows} cols={conditionCols} maxRows={6} striped />
        </div>
      ) : (
        <EmptyState title="Conditional rows unavailable" message="This product needs replay-compatible fair and mid rows for residual condition tables." />
      )}
      {panel.messages.length > 0 && (
        <div className="space-y-2">
          {panel.messages.map((message) => (
            <div key={message} className="rounded-lg border border-border bg-bg/30 px-4 py-3 text-xs leading-5 text-muted">
              {message}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MetricGrid({ metrics }: { metrics: AlphaMetric[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {metrics.map((metric) => (
        <div key={`${metric.label}-${metric.value}`} className="rounded-lg border border-border bg-bg/30 px-4 py-3">
          <div className="hud-label text-muted">{metric.label}</div>
          <div className={`font-display mt-2 truncate text-sm font-bold uppercase tracking-[0.06em] ${toneText[metric.tone ?? 'neutral']}`}>
            {metric.value}
          </div>
          {metric.detail && <div className="mt-2 text-xs leading-5 text-muted">{metric.detail}</div>}
        </div>
      ))}
    </div>
  )
}

function HypothesisLine({ item }: { item: AlphaHypothesis }) {
  return (
    <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-xs font-semibold text-txt">{item.name}</div>
          <div className="hud-label mt-2 text-muted">{item.product} / {item.category}</div>
        </div>
        <span className={`font-mono text-xs ${toneText[priorityTone(item.priorityLabel)]}`}>{Math.round(item.priorityScore)}</span>
      </div>
      <div className="mt-3">
        <ClassBadge item={item} />
      </div>
    </div>
  )
}

function EvidencePanel({ item }: { item: AlphaHypothesis }) {
  return (
    <div className="rounded-lg border border-border bg-bg/30 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-display text-sm font-semibold uppercase tracking-[0.08em] text-txt">{item.name}</div>
          <div className="hud-label mt-2 text-muted">{item.product} / {item.category}</div>
        </div>
        <ClassBadge item={item} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <MiniStat label="Confidence" value={fmtPct(item.confidence)} tone={confidenceTone(item.confidence)} />
        <MiniStat label="Support" value={item.sampleSize == null ? '-' : fmtInt(item.sampleSize)} />
        <MiniStat label="Priority" value={`${item.priorityLabel} ${Math.round(item.priorityScore)}`} tone={priorityTone(item.priorityLabel)} />
        <MiniStat label="Action" value={ALPHA_ACTION_LABELS[item.nextAction]} tone={item.nextAction === 'reject' ? 'bad' : item.nextAction === 'ab_on_website' ? 'warn' : 'accent'} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <EvidenceList title="Support" items={item.supportEvidence} />
        <EvidenceList title="Against" items={item.againstEvidence} />
      </div>

      <div className="mt-4 rounded-lg border border-border bg-white/[0.02] p-3 text-xs leading-5 text-muted">
        {item.nextActionDetail}
      </div>
    </div>
  )
}

function EvidenceList({ title, items }: { title: string; items: AlphaEvidence[] }) {
  return (
    <div>
      <div className="hud-label mb-3 text-accent">{title}</div>
      <div className="space-y-2">
        {items.length > 0 ? items.map((item) => (
          <div key={`${title}-${item.label}-${item.value}`} className="rounded-lg border border-border bg-white/[0.02] px-3 py-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted">{item.label}</span>
              <span className={`font-mono text-xs ${toneText[item.tone ?? 'neutral']}`}>{item.value}</span>
            </div>
            {item.detail && <div className="mt-1 text-[0.72rem] leading-5 text-muted">{item.detail}</div>}
          </div>
        )) : (
          <div className="text-xs text-muted">No evidence rows present.</div>
        )}
      </div>
    </div>
  )
}

function MiniStat({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: AlphaTone }) {
  return (
    <div className="rounded-lg border border-border bg-white/[0.02] px-3 py-2">
      <div className="hud-label text-muted">{label}</div>
      <div className={`font-mono mt-2 text-xs ${toneText[tone]}`}>{value}</div>
    </div>
  )
}

function ClassBadge({ item }: { item: AlphaHypothesis }) {
  return (
    <span className={`inline-flex rounded border px-2 py-1 font-mono text-[0.68rem] uppercase tracking-[0.12em] ${classBadge[item.classification]}`}>
      {ALPHA_CLASS_LABELS[item.classification]}
    </span>
  )
}

function toneForPriority(label: AlphaHypothesis['priorityLabel']): 'good' | 'bad' | 'warn' | 'neutral' | 'accent' {
  if (label === 'High') return 'good'
  if (label === 'Medium') return 'accent'
  if (label === 'Low') return 'warn'
  return 'neutral'
}

function priorityTone(label: AlphaHypothesis['priorityLabel']): AlphaTone {
  if (label === 'High') return 'good'
  if (label === 'Medium') return 'accent'
  if (label === 'Low') return 'warn'
  return 'neutral'
}

function confidenceTone(value: number | null): AlphaTone {
  if (value == null) return 'neutral'
  if (value >= 0.68) return 'good'
  if (value >= 0.45) return 'warn'
  return 'neutral'
}

function valueTone(value: number): 'good' | 'bad' | 'neutral' {
  if (!Number.isFinite(value)) return 'neutral'
  if (value > 0) return 'good'
  if (value < 0) return 'bad'
  return 'neutral'
}

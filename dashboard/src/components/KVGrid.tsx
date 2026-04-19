import { clsx } from 'clsx'

interface KVPair {
  label: string
  value: string | number | null | undefined
  tone?: 'good' | 'bad' | 'warn' | 'neutral' | 'accent'
}

interface Props {
  pairs: KVPair[]
  cols?: 1 | 2 | 3 | 4
  className?: string
}

const toneClass = {
  good: 'text-good',
  bad: 'text-bad',
  warn: 'text-warn',
  neutral: 'text-txt-soft',
  accent: 'text-accent',
}

const colClass = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 sm:grid-cols-2',
  3: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3',
  4: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-4',
}

export function KVGrid({ pairs, cols = 2, className }: Props) {
  return (
    <div className={clsx('grid gap-3', colClass[cols], className)}>
      {pairs.map(({ label, value, tone = 'neutral' }, i) => (
        <div key={i} className="rounded-lg border border-border bg-white/[0.025] px-3 py-3">
          <div className="hud-label mb-1 text-muted">{label}</div>
          <div className={clsx('font-mono text-sm tracking-wide', toneClass[tone])}>
            {value == null ? '-' : String(value)}
          </div>
        </div>
      ))}
    </div>
  )
}

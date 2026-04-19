import { clsx } from 'clsx'

type Tone = 'good' | 'bad' | 'warn' | 'neutral' | 'accent'

interface Props {
  label: string
  value: string | number
  sub?: string
  tone?: Tone
  delta?: string
  deltaTone?: Tone
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const toneColor: Record<Tone, string> = {
  good: 'text-good',
  bad: 'text-bad',
  warn: 'text-warn',
  neutral: 'text-txt',
  accent: 'text-accent',
}

const valueSizes = {
  sm: 'text-2xl',
  md: 'text-[2rem]',
  lg: 'text-[2.7rem]',
}

export function MetricCard({
  label,
  value,
  sub,
  tone = 'neutral',
  delta,
  deltaTone,
  size = 'md',
  className,
}: Props) {
  return (
    <div
      className={clsx(
        'glass-panel group rounded-lg p-5 transition-all duration-500 ease-observatory hover:-translate-y-0.5 hover:border-border-2 hover:shadow-card-hover',
        className,
      )}
    >
      <div className="hud-label text-muted">{label}</div>
      <div className={clsx('font-display mt-3 font-bold leading-none tracking-normal', valueSizes[size], toneColor[tone])}>
        {typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value}
      </div>
      {(sub || delta) && (
        <div className="mt-3 flex items-end gap-3 border-t border-border pt-3">
          {sub && <div className="min-w-0 text-xs leading-5 text-muted">{sub}</div>}
          {delta && (
            <div className={clsx('font-mono ml-auto whitespace-nowrap text-[0.68rem]', deltaTone ? toneColor[deltaTone] : 'text-muted')}>
              {delta}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

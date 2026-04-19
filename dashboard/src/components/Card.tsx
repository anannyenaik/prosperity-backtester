import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface Props {
  title?: string
  subtitle?: string
  kicker?: string
  children: ReactNode
  className?: string
  bodyClass?: string
  action?: ReactNode
}

export function Card({ title, subtitle, kicker, children, className, bodyClass, action }: Props) {
  return (
    <section className={clsx('glass-panel rounded-lg flex min-w-0 flex-col', className)}>
      {(title || kicker || action) && (
        <header className="relative z-10 flex items-start justify-between gap-4 border-b border-border px-5 pb-4 pt-5">
          <div className="min-w-0">
            {kicker && <div className="hud-label chapter-rule mb-3 text-accent">{kicker}</div>}
            {title && (
              <h2 className="font-display text-[1.02rem] font-semibold uppercase leading-tight tracking-[0.08em] text-txt">
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-1 max-w-3xl text-sm leading-6 text-muted">{subtitle}</p>}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      <div className={clsx('relative z-10 min-w-0 flex-1 p-5', bodyClass)}>{children}</div>
    </section>
  )
}

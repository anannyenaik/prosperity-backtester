import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface Props {
  icon?: ReactNode
  title?: string
  message?: string
  action?: ReactNode
  className?: string
}

export function EmptyState({ icon, title = 'Data not present', message, action, className }: Props) {
  return (
    <div className={clsx('flex flex-col items-center justify-center gap-3 px-6 py-12 text-center', className)}>
      {icon && <div className="text-accent opacity-65">{icon}</div>}
      <div className="font-display text-sm font-semibold uppercase tracking-[0.12em] text-txt">{title}</div>
      {message && <div className="max-w-sm text-sm leading-6 text-muted">{message}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

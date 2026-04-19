import type { ReactNode } from 'react'

interface Props {
  kicker: string
  title: string
  accent?: string
  description?: string
  meta?: ReactNode
  action?: ReactNode
}

export function PageHeader({ kicker, title, accent, description, meta, action }: Props) {
  return (
    <header className="mb-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
      <div className="min-w-0">
        <div className="hud-label chapter-rule mb-4 text-accent">{kicker}</div>
        <h1 className="font-display max-w-5xl text-[2.3rem] font-extrabold uppercase leading-[0.9] tracking-normal text-txt md:text-[4rem]">
          {title}
          {accent && <em className="font-serif ml-3 font-light normal-case tracking-normal text-accent-2">{accent}</em>}
        </h1>
        {description && <p className="mt-4 max-w-3xl text-lg leading-8 text-txt-soft">{description}</p>}
        {meta && <div className="mt-5">{meta}</div>}
      </div>
      {action && <div className="lg:justify-self-end">{action}</div>}
    </header>
  )
}

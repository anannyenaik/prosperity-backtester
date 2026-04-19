import { useState } from 'react'
import { clsx } from 'clsx'
import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react'
import { fmtInt, fmtNum } from '../lib/format'

export type CellTone = 'good' | 'bad' | 'warn' | 'neutral' | 'accent'

export interface ColDef<T> {
  key: keyof T | string
  header: string
  fmt?: 'num' | 'int' | 'pct' | 'str' | 'raw'
  digits?: number
  align?: 'left' | 'right' | 'center'
  width?: number
  tone?: (v: unknown, row: T) => CellTone
  render?: (v: unknown, row: T) => string | number | React.ReactNode
  sortable?: boolean
}

interface Props<T extends object> {
  rows: T[]
  cols: ColDef<T>[]
  maxRows?: number
  striped?: boolean
  className?: string
  emptyMsg?: string
}

function getValue<T>(row: T, key: string): unknown {
  const parts = key.split('.')
  let cur: unknown = row
  for (const p of parts) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[p]
  }
  return cur
}

function formatCell<T>(col: ColDef<T>, v: unknown, row: T): string | number | React.ReactNode {
  if (col.render) return col.render(v, row)
  if (v == null) return '-'
  const n = Number(v)
  if (col.fmt === 'int') return fmtInt(n)
  if (col.fmt === 'num') return fmtNum(n, col.digits ?? 2)
  if (col.fmt === 'pct') return Number.isNaN(n) ? '-' : (n * 100).toFixed(col.digits ?? 1) + '%'
  if (col.fmt === 'raw') return String(v)
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1000) return fmtNum(v, 0)
    return fmtNum(v, col.digits ?? 2)
  }
  return String(v)
}

const toneClass: Record<CellTone, string> = {
  good: 'text-good',
  bad: 'text-bad',
  warn: 'text-warn',
  neutral: 'text-txt-soft',
  accent: 'text-accent',
}

export function DataTable<T extends object>({
  rows,
  cols,
  maxRows = 100,
  striped = true,
  className,
  emptyMsg = 'No rows',
}: Props<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortAsc, setSortAsc] = useState(true)

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortAsc((p) => !p)
      return
    }
    setSortKey(key)
    setSortAsc(true)
  }

  const sorted = sortKey
    ? [...rows].sort((a, b) => {
        const av = getValue(a, sortKey) ?? ''
        const bv = getValue(b, sortKey) ?? ''
        const n1 = Number(av)
        const n2 = Number(bv)
        if (!Number.isNaN(n1) && !Number.isNaN(n2)) return sortAsc ? n1 - n2 : n2 - n1
        return sortAsc ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av))
      })
    : rows

  const visible = sorted.slice(0, maxRows)

  return (
    <div className={clsx('overflow-auto rounded-lg border border-border bg-bg/35', className)}>
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            {cols.map((col) => {
              const colKey = String(col.key)
              const isSorted = sortKey === colKey
              const Ico = isSorted ? (sortAsc ? ChevronUp : ChevronDown) : ChevronsUpDown
              return (
                <th
                  key={colKey}
                  onClick={() => col.sortable !== false && toggleSort(colKey)}
                  style={{ width: col.width }}
                  className={clsx(
                    'hud-label sticky top-0 z-10 border-b border-border bg-surface-2 px-3 py-3 text-muted',
                    col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left',
                    col.sortable !== false && 'cursor-pointer hover:text-accent',
                  )}
                >
                  <span className="inline-flex items-center gap-1.5">
                    {col.header}
                    {col.sortable !== false && (
                      <Ico className={clsx('h-3 w-3 shrink-0', isSorted ? 'text-accent' : 'opacity-35')} />
                    )}
                  </span>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 && (
            <tr>
              <td colSpan={cols.length} className="px-4 py-10 text-center text-muted">
                {emptyMsg}
              </td>
            </tr>
          )}
          {visible.map((row, ri) => (
            <tr
              key={ri}
              className={clsx(
                'border-b border-border transition-colors last:border-0 hover:bg-accent/5',
                striped && ri % 2 === 0 ? 'bg-white/[0.012]' : 'bg-transparent',
              )}
            >
              {cols.map((col) => {
                const colKey = String(col.key)
                const v = getValue(row, colKey)
                const formatted = formatCell(col, v, row)
                const tone = col.tone?.(v, row) ?? 'neutral'
                return (
                  <td
                    key={colKey}
                    className={clsx(
                      'font-mono whitespace-nowrap px-3 py-2.5 text-[0.72rem]',
                      col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left',
                      toneClass[tone],
                    )}
                  >
                    {formatted}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length > maxRows && (
        <div className="hud-label border-t border-border bg-surface-2 px-3 py-2 text-muted">
          Showing {maxRows} of {sorted.length} rows
        </div>
      )}
    </div>
  )
}

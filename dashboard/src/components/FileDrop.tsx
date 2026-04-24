import { useCallback, useRef, useState } from 'react'
import type React from 'react'
import { Upload } from 'lucide-react'
import { clsx } from 'clsx'
import { useStore } from '../store'
import type { DashboardPayload } from '../types'

export function FileDrop() {
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const loadRun = useStore((s) => s.loadRun)

  const parseFiles = useCallback(
    async (files: FileList | File[]) => {
      setLoading(true)
      setError(null)
      const arr = Array.from(files)
      const errors: string[] = []
      for (const file of arr) {
        try {
          const text = await file.text()
          const payload = JSON.parse(text) as DashboardPayload
          loadRun(payload, file.name)
        } catch (e) {
          errors.push(`${file.name}: ${e instanceof Error ? e.message : String(e)}`)
        }
      }
      setLoading(false)
      if (errors.length) setError(errors.join('\n'))
    },
    [loadRun],
  )

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragging(false)
      parseFiles(e.dataTransfer.files)
    },
    [parseFiles],
  )

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(true)
  }, [])

  const onDragLeave = useCallback(() => setDragging(false), [])

  return (
    <div
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          inputRef.current?.click()
        }
      }}
      role="button"
      tabIndex={0}
      data-interactive="true"
      className={clsx(
        'file-drop group relative flex items-center gap-2.5 overflow-hidden rounded-lg border border-dashed px-3 py-2.5 text-left transition-all duration-500 ease-observatory',
        dragging
          ? 'border-accent bg-accent/10 shadow-glow'
          : 'border-border-2 bg-white/[0.025] hover:border-accent/45 hover:bg-accent/5',
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        multiple
        hidden
        onChange={(e) => {
          if (e.target.files) parseFiles(e.target.files)
        }}
      />
      <div className="file-drop__icon grid h-[34px] w-[34px] shrink-0 place-items-center rounded-lg border border-border bg-bg/55 text-accent transition-colors duration-500 group-hover:border-accent/40">
        {loading ? <div className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" /> : <Upload className="h-4 w-4" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="file-drop__title font-display text-[0.76rem] font-semibold uppercase tracking-[0.08em] text-txt">
          {dragging ? 'Drop dashboard bundles' : 'Drop dashboard.json files'}
        </div>
        <div className="file-drop__copy mt-0.5 truncate text-[11px] leading-[1.35] text-muted">
          Browse or drag one workspace bundle, or any replay, Monte Carlo, calibration, comparison or Round 2 bundle.
        </div>
      </div>
      {error && (
        <pre className="absolute left-0 right-0 top-full mt-2 whitespace-pre-wrap rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-left font-mono text-[11px] text-bad">
          {error}
        </pre>
      )}
    </div>
  )
}

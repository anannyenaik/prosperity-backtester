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
      className={clsx(
        'rounded-lg border border-dashed p-7 text-center transition-all duration-500 ease-observatory',
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
      <div className="mx-auto grid h-14 w-14 place-items-center rounded-lg border border-border bg-bg/55 text-accent">
        {loading ? <div className="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" /> : <Upload className="h-6 w-6" />}
      </div>
      <div className="font-display mt-4 text-sm font-semibold uppercase tracking-[0.1em] text-txt">
        {dragging ? 'Drop dashboard bundles' : 'Drop dashboard.json files'}
      </div>
      <div className="mt-2 text-sm leading-6 text-muted">
        Browse or drag replay, Monte Carlo, calibration, comparison and optimisation bundles.
      </div>
      {error && (
        <pre className="mt-4 whitespace-pre-wrap rounded-lg border border-bad/25 bg-bad/10 px-3 py-2 text-left font-mono text-xs text-bad">
          {error}
        </pre>
      )}
    </div>
  )
}

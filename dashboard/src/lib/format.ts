export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '-'
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '-'
  return Math.round(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '-'
  return (v * 100).toFixed(digits) + '%'
}

export function fmtPctRaw(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '-'
  return v.toFixed(digits) + '%'
}

export function fmtShort(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '-'
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return (v / 1_000_000).toFixed(2) + 'M'
  if (abs >= 1_000) return (v / 1_000).toFixed(1) + 'k'
  return fmtNum(v, 1)
}

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '-'
  return v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 1 })
}

export function fmtBytes(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '-'
  const abs = Math.abs(v)
  if (abs >= 1_000_000_000) return (v / 1_000_000_000).toFixed(2) + ' GB'
  if (abs >= 1_000_000) return (v / 1_000_000).toFixed(2) + ' MB'
  if (abs >= 1_000) return (v / 1_000).toFixed(1) + ' KB'
  return Math.round(v) + ' B'
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function colorForValue(v: number | null | undefined): 'good' | 'bad' | 'neutral' {
  if (v == null || !Number.isFinite(v)) return 'neutral'
  if (v > 0) return 'good'
  if (v < 0) return 'bad'
  return 'neutral'
}

export function axisTickFmt(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
  if (abs >= 1_000) return (v / 1_000).toFixed(0) + 'k'
  return String(Math.round(v))
}

export function fmtTimestamp(global: number): string {
  const dayBucket = Math.floor(global / 1_000_000)
  const ts = global % 1_000_000
  const day = dayBucket - 3
  const dayLabel = day === 0 ? 'D0' : day > 0 ? `D+${day}` : `D${day}`
  return `${dayLabel} t${ts}`
}

export function truncateStr(s: string, max = 24): string {
  return s.length > max ? s.slice(0, max - 1) + '...' : s
}

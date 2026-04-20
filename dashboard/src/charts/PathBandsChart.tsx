import {
  Area,
  Line,
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { BandPoint } from '../lib/data'
import { axisTickFmt, fmtNum } from '../lib/format'
import { C, GRID, AXIS_TEXT, CHART_MARGINS, TOOLTIP_BG, TOOLTIP_BORDER, CHART_HEIGHT } from './theme'

interface Props {
  data: BandPoint[]
  height?: number
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload ?? {}
  const get = (key: string) => row[key] ?? payload.find((p: any) => p.dataKey === key || p.name === key)?.value
  return (
    <div
      style={{
        background: TOOLTIP_BG,
        border: `1px solid ${TOOLTIP_BORDER}`,
        borderRadius: 8,
        padding: '10px 14px',
        fontSize: 12,
        lineHeight: 1.7,
        minWidth: 160,
      }}
    >
      <div style={{ color: AXIS_TEXT, marginBottom: 4, fontSize: 11 }}>t={label?.toLocaleString()}</div>
      {[['P10', 'p10'], ['P25', 'p25'], ['P50 (median)', 'p50'], ['P75', 'p75'], ['P90', 'p90']].map(([lbl, key]) => {
        const v = get(key)
        return v != null ? (
          <div key={key} style={{ display: 'flex', justifyContent: 'space-between', gap: 14 }}>
            <span style={{ color: AXIS_TEXT }}>{lbl}</span>
            <span style={{ color: '#e4dbc9' }}>{fmtNum(v, 1)}</span>
          </div>
        ) : null
      })}
    </div>
  )
}

export function PathBandsChart({ data, height = CHART_HEIGHT }: Props) {
  if (!data.length) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: AXIS_TEXT, fontSize: 13 }}>
        Data not present in this bundle
      </div>
    )
  }

  // Range areas show the outer P10-P90 band and the tighter P25-P75 band.
  const chartData = data.map((d) => ({
    ts: d.ts,
    p10: d.p10,
    p25: d.p25,
    p75: d.p75,
    p90: d.p90,
    band_outer: [d.p10, d.p90] as [number, number],
    band_inner: [d.p25, d.p75] as [number, number],
    p50: d.p50,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={chartData} margin={CHART_MARGINS}>
        <defs>
          <linearGradient id="bandGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.total} stopOpacity={0.25} />
            <stop offset="100%" stopColor={C.total} stopOpacity={0.05} />
          </linearGradient>
          <linearGradient id="bandInnerGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.pepper} stopOpacity={0.22} />
            <stop offset="100%" stopColor={C.pepper} stopOpacity={0.06} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} strokeOpacity={0.6} vertical={false} />
        <XAxis
          dataKey="ts"
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          tickFormatter={axisTickFmt}
          minTickGap={60}
        />
        <YAxis
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={axisTickFmt}
          width={52}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey="band_outer"
          name="P10-P90"
          stroke="none"
          fill="url(#bandGrad)"
          fillOpacity={1}
          dot={false}
          activeDot={false}
        />
        <Area
          type="monotone"
          dataKey="band_inner"
          name="P25-P75"
          stroke="none"
          fill="url(#bandInnerGrad)"
          fillOpacity={1}
          dot={false}
          activeDot={false}
        />
        <Line
          type="monotone"
          dataKey="p50"
          name="P50 (median)"
          stroke={C.total}
          strokeWidth={2.5}
          dot={false}
          activeDot={{ r: 3, fill: C.total }}
        />
        <Legend
          wrapperStyle={{ fontSize: 11, color: AXIS_TEXT, paddingTop: 8 }}
          iconType="plainline"
          iconSize={14}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

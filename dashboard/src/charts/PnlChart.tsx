import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts'
import type { PnlPoint } from '../lib/data'
import { axisTickFmt, fmtNum } from '../lib/format'
import { C, GRID, AXIS_TEXT, CHART_MARGINS, TOOLTIP_BG, TOOLTIP_BORDER, CHART_HEIGHT } from './theme'

interface Props {
  data: PnlPoint[]
  height?: number
  showRealised?: boolean
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
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
      <div style={{ color: AXIS_TEXT, marginBottom: 6, fontSize: 11 }}>t={label?.toLocaleString()}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <span style={{ color: p.color }}>{p.name}</span>
          <span style={{ color: '#e4dbc9', fontVariantNumeric: 'tabular-nums' }}>
            {fmtNum(p.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

export function PnlChart({ data, height = CHART_HEIGHT, showRealised = true }: Props) {
  if (!data.length) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: AXIS_TEXT, fontSize: 13 }}>
        No data
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={CHART_MARGINS}>
        <defs>
          <linearGradient id="gradMtm" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={C.total} stopOpacity={0.25} />
            <stop offset="95%" stopColor={C.total} stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="gradRealised" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={C.realised} stopOpacity={0.2} />
            <stop offset="95%" stopColor={C.realised} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} strokeOpacity={0.6} vertical={false} />
        <XAxis
          dataKey="ts"
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          tickFormatter={(v) => axisTickFmt(v)}
          minTickGap={60}
        />
        <YAxis
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={axisTickFmt}
          width={52}
        />
        <ReferenceLine y={0} stroke={C.neutral} strokeDasharray="4 4" strokeOpacity={0.5} />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: AXIS_TEXT, paddingTop: 8 }}
          iconType="plainline"
          iconSize={14}
        />
        <Area
          type="monotone"
          dataKey="mtm"
          name="MTM"
          stroke={C.total}
          strokeWidth={2}
          fill="url(#gradMtm)"
          dot={false}
          activeDot={{ r: 3, fill: C.total }}
        />
        {showRealised && (
          <Area
            type="monotone"
            dataKey="realised"
            name="Realised"
            stroke={C.realised}
            strokeWidth={1.5}
            fill="url(#gradRealised)"
            dot={false}
            activeDot={{ r: 3, fill: C.realised }}
            strokeDasharray="5 3"
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  )
}

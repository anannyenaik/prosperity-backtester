import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Cell,
  ResponsiveContainer,
} from 'recharts'
import type { HistPoint } from '../lib/data'
import { fmtNum } from '../lib/format'
import { C, GRID, AXIS_TEXT, CHART_MARGINS, TOOLTIP_BG, TOOLTIP_BORDER, CHART_HEIGHT } from './theme'

interface Props {
  data: HistPoint[]
  color?: string
  referenceAt?: number
  height?: number
  label?: string
}

function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]
  return (
    <div
      style={{
        background: TOOLTIP_BG,
        border: `1px solid ${TOOLTIP_BORDER}`,
        borderRadius: 8,
        padding: '10px 14px',
        fontSize: 12,
        lineHeight: 1.7,
      }}
    >
      <div style={{ color: AXIS_TEXT }}>{d.payload?.label}</div>
      <div style={{ color: '#e4dbc9' }}>
        Count: <strong>{d.value}</strong>
      </div>
      <div style={{ color: AXIS_TEXT, fontSize: 11 }}>
        Centre: {fmtNum(d.payload?.midpoint)}
      </div>
    </div>
  )
}

export function HistogramChart({ data, color = C.total, referenceAt, height = CHART_HEIGHT, label }: Props) {
  if (!data.length) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: AXIS_TEXT, fontSize: 13 }}>
        No data
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={CHART_MARGINS} barCategoryGap={1}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} strokeOpacity={0.6} vertical={false} />
        <XAxis
          dataKey="midpoint"
          type="number"
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          tickFormatter={(v) => String(Math.round(v))}
          domain={['dataMin', 'dataMax']}
          minTickGap={40}
        />
        <YAxis
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          width={36}
        />
        <Tooltip content={<CustomTooltip />} />
        {referenceAt != null && (
          <ReferenceLine x={referenceAt} stroke={C.warn} strokeDasharray="4 4" strokeWidth={1.5} />
        )}
        <Bar dataKey="count" name={label ?? 'Count'} radius={[2, 2, 0, 0]}>
          {data.map((entry, i) => (
            <Cell
              key={i}
              fill={entry.midpoint < 0 ? C.bad : color}
              opacity={0.85}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

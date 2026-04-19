import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Legend,
  Cell,
  ResponsiveContainer,
} from 'recharts'
import { fmtNum, axisTickFmt } from '../lib/format'
import { C, GRID, AXIS_TEXT, CHART_MARGINS, TOOLTIP_BG, TOOLTIP_BORDER, CHART_HEIGHT } from './theme'

interface BarSeries {
  key: string
  name: string
  color: string
}

interface Props {
  data: Record<string, unknown>[]
  labelKey: string
  series: BarSeries[]
  height?: number
  horizontal?: boolean
  colorByValue?: boolean
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
      <div style={{ color: AXIS_TEXT, marginBottom: 6 }}>{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ display: 'flex', justifyContent: 'space-between', gap: 14 }}>
          <span style={{ color: p.fill }}>{p.name}</span>
          <span style={{ color: '#e4dbc9' }}>{fmtNum(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

export function BarGroupChart({
  data,
  labelKey,
  series,
  height = CHART_HEIGHT,
  colorByValue = false,
}: Props) {
  if (!data.length) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: AXIS_TEXT, fontSize: 13 }}>
        No data
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={CHART_MARGINS} barCategoryGap="20%">
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} strokeOpacity={0.6} vertical={false} />
        <XAxis
          dataKey={labelKey}
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          interval={0}
          minTickGap={0}
        />
        <YAxis
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={axisTickFmt}
          width={52}
        />
        <ReferenceLine y={0} stroke={C.neutral} strokeOpacity={0.3} />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: AXIS_TEXT, paddingTop: 8 }}
          iconType="square"
          iconSize={10}
        />
        {series.map((s) => (
          <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} radius={[3, 3, 0, 0]} opacity={0.9}>
            {colorByValue &&
              data.map((_, i) => {
                const v = data[i][s.key] as number
                return <Cell key={i} fill={v >= 0 ? C.good : C.bad} />
              })}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

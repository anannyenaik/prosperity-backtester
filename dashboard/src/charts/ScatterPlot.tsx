import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { fmtNum } from '../lib/format'
import { C, GRID, AXIS_TEXT, CHART_MARGINS, TOOLTIP_BG, TOOLTIP_BORDER, CHART_HEIGHT } from './theme'

interface ScatterDataset {
  name: string
  color: string
  data: { x: number; y: number; label?: string }[]
}

interface Props {
  datasets: ScatterDataset[]
  xLabel?: string
  yLabel?: string
  xRefAt?: number
  yRefAt?: number
  height?: number
}

function CustomTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
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
      {d?.label && <div style={{ color: AXIS_TEXT, marginBottom: 4 }}>{d.label}</div>}
      <div>
        <span style={{ color: AXIS_TEXT }}>X: </span>
        <span style={{ color: '#e4dbc9' }}>{fmtNum(d?.x)}</span>
      </div>
      <div>
        <span style={{ color: AXIS_TEXT }}>Y: </span>
        <span style={{ color: '#e4dbc9' }}>{fmtNum(d?.y)}</span>
      </div>
    </div>
  )
}

export function ScatterPlot({ datasets, xLabel, yLabel, xRefAt, yRefAt, height = CHART_HEIGHT }: Props) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ ...CHART_MARGINS, left: 16, bottom: xLabel ? 24 : 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} strokeOpacity={0.6} />
        <XAxis
          dataKey="x"
          type="number"
          name={xLabel}
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          label={xLabel ? { value: xLabel, position: 'insideBottom', offset: -12, fill: AXIS_TEXT, fontSize: 11 } : undefined}
        />
        <YAxis
          dataKey="y"
          type="number"
          name={yLabel}
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          label={yLabel ? { value: yLabel, angle: -90, position: 'insideLeft', fill: AXIS_TEXT, fontSize: 11 } : undefined}
          width={52}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: AXIS_TEXT, paddingTop: 8 }}
          iconType="circle"
          iconSize={8}
        />
        {xRefAt != null && (
          <ReferenceLine x={xRefAt} stroke={C.neutral} strokeDasharray="4 4" strokeOpacity={0.5} />
        )}
        {yRefAt != null && (
          <ReferenceLine y={yRefAt} stroke={C.neutral} strokeDasharray="4 4" strokeOpacity={0.5} />
        )}
        {datasets.map((ds) => (
          <Scatter key={ds.name} name={ds.name} data={ds.data} fill={ds.color} opacity={0.8} r={4} />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  )
}

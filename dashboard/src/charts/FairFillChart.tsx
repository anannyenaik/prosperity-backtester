import {
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { FairPoint, FillPoint } from '../lib/data'
import { axisTickFmt, fmtNum } from '../lib/format'
import { C, GRID, AXIS_TEXT, CHART_MARGINS, TOOLTIP_BG, TOOLTIP_BORDER, CHART_HEIGHT } from './theme'

interface Props {
  fair: FairPoint[]
  fills: FillPoint[]
  height?: number
}

function CustomTooltip({ active, payload }: any) {
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
        minWidth: 150,
      }}
    >
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ color: p.color ?? AXIS_TEXT }}>{p.name}</span>
          <span style={{ color: '#e4dbc9' }}>{fmtNum(p.value, 1)}</span>
        </div>
      ))}
    </div>
  )
}

export function FairFillChart({ fair, fills, height = CHART_HEIGHT }: Props) {
  // Merge fair + fills on same x-axis (ts)
  // Build a combined dataset for the line, and separate scatter data for fills
  const buyFills = fills.filter((f) => f.side === 'buy').map((f) => ({ ts: f.ts, buy: f.price }))
  const sellFills = fills.filter((f) => f.side === 'sell').map((f) => ({ ts: f.ts, sell: f.price }))

  if (!fair.length) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: AXIS_TEXT, fontSize: 13 }}>
        Data not present in this bundle
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart margin={CHART_MARGINS}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} strokeOpacity={0.6} vertical={false} />
        <XAxis
          dataKey="ts"
          type="number"
          domain={['dataMin', 'dataMax']}
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
          width={56}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          wrapperStyle={{ fontSize: 11, color: AXIS_TEXT, paddingTop: 8 }}
          iconType="plainline"
          iconSize={14}
        />
        <Line
          data={fair}
          type="monotone"
          dataKey="analysis_fair"
          name="Analysis Fair"
          stroke={C.fair}
          strokeWidth={2}
          dot={false}
          activeDot={false}
        />
        <Line
          data={fair}
          type="monotone"
          dataKey="mid"
          name="Mid"
          stroke={C.mid}
          strokeWidth={1}
          dot={false}
          activeDot={false}
          strokeDasharray="3 3"
          strokeOpacity={0.7}
        />
        <Scatter
          data={buyFills}
          dataKey="buy"
          name="Buy Fill"
          fill={C.fillBuy}
          opacity={0.9}
          r={3}
        />
        <Scatter
          data={sellFills}
          dataKey="sell"
          name="Sell Fill"
          fill={C.fillSell}
          opacity={0.9}
          r={3}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

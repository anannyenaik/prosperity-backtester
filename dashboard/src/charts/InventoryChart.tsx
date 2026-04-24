import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import type { InventoryPoint } from '../lib/data'
import { POSITION_LIMIT } from '../lib/data'
import { axisTickFmt, fmtNum } from '../lib/format'
import { C, GRID, AXIS_TEXT, CHART_MARGINS, TOOLTIP_BG, TOOLTIP_BORDER, CHART_HEIGHT } from './theme'

interface Props {
  data: InventoryPoint[]
  height?: number
  showCapZones?: boolean
  product?: string
  positionLimit?: number
}

function CustomTooltip({ active, payload, positionLimit }: any) {
  if (!active || !payload?.length) return null
  const pos = payload.find((p: any) => p.dataKey === 'position')
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
      {pos && (
        <div style={{ color: C.total }}>
          Position: <strong style={{ color: '#e4dbc9' }}>{fmtNum(pos.value, 0)}</strong>
          <span style={{ color: AXIS_TEXT, marginLeft: 8 }}>
            ({positionLimit > 0 ? ((Math.abs(pos.value) / positionLimit) * 100).toFixed(0) : '0'}% of cap)
          </span>
        </div>
      )}
    </div>
  )
}

export function InventoryChart({ data, height = CHART_HEIGHT, showCapZones = true, positionLimit = POSITION_LIMIT }: Props) {
  if (!data.length) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: AXIS_TEXT, fontSize: 13 }}>
        Data not present in this bundle
      </div>
    )
  }

  const capColorFill = 'rgba(240,80,96,0.06)'

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={CHART_MARGINS}>
        <defs>
          <linearGradient id="gradPos" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.total} stopOpacity={0.2} />
            <stop offset="100%" stopColor={C.total} stopOpacity={0.02} />
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
          domain={[-(positionLimit + 8), positionLimit + 8]}
          tick={{ fill: AXIS_TEXT, fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={axisTickFmt}
          width={40}
        />
        <Tooltip content={<CustomTooltip positionLimit={positionLimit} />} />
        {showCapZones && (
          <>
            <ReferenceLine y={positionLimit} stroke={C.capLine} strokeDasharray="5 3" strokeWidth={1.5} strokeOpacity={0.7} label={{ value: `+${positionLimit}`, position: 'right', fill: C.capLine, fontSize: 10 }} />
            <ReferenceLine y={-positionLimit} stroke={C.capLine} strokeDasharray="5 3" strokeWidth={1.5} strokeOpacity={0.7} label={{ value: `-${positionLimit}`, position: 'right', fill: C.capLine, fontSize: 10 }} />
          </>
        )}
        <ReferenceLine y={0} stroke={C.neutral} strokeOpacity={0.3} />
        <Area
          type="monotone"
          dataKey="position"
          name="Position"
          stroke={C.total}
          strokeWidth={2}
          fill="url(#gradPos)"
          dot={false}
          activeDot={{ r: 3, fill: C.total }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

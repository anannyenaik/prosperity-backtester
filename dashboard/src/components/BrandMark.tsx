import { clsx } from 'clsx'

interface BrandMarkProps {
  size?: number
  className?: string
}

const OUTER_HEX = '0,-17 14.72,-8.5 14.72,8.5 0,17 -14.72,8.5 -14.72,-8.5'
const INNER_HEX = '0,-9 7.79,-4.5 7.79,4.5 0,9 -7.79,4.5 -7.79,-4.5'
const OUTER_NODES: ReadonlyArray<[number, number]> = [
  [0, -17],
  [14.72, -8.5],
  [14.72, 8.5],
  [0, 17],
  [-14.72, 8.5],
  [-14.72, -8.5],
]

export function BrandMark({ size = 40, className }: BrandMarkProps) {
  return (
    <div
      className={clsx('brand-mark', className)}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox="-22 -22 44 44" width={size} height={size} role="presentation">
        <defs>
          <radialGradient id="brand-core" cx="0" cy="0" r="0.5">
            <stop offset="0%" stopColor="rgba(125,231,255,0.95)" />
            <stop offset="45%" stopColor="rgba(125,231,255,0.32)" />
            <stop offset="100%" stopColor="rgba(125,231,255,0)" />
          </radialGradient>
          <linearGradient id="brand-ring" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="rgba(125,231,255,0.9)" />
            <stop offset="50%" stopColor="rgba(199,171,102,0.78)" />
            <stop offset="100%" stopColor="rgba(125,231,255,0.9)" />
          </linearGradient>
          <linearGradient id="brand-ring-soft" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="rgba(228,219,201,0.45)" />
            <stop offset="100%" stopColor="rgba(228,219,201,0.08)" />
          </linearGradient>
        </defs>

        <circle r="11.5" cx="0" cy="0" fill="url(#brand-core)" className="brand-mark__core" />

        <g className="brand-mark__ring">
          <polygon
            points={OUTER_HEX}
            fill="none"
            stroke="url(#brand-ring)"
            strokeWidth="1.1"
            strokeLinejoin="round"
          />
          {OUTER_NODES.map(([x, y], index) => (
            <circle
              key={index}
              cx={x}
              cy={y}
              r="1.25"
              fill="rgba(228,219,201,0.92)"
              className="brand-mark__node"
              style={{ animationDelay: `${index * 0.35}s` }}
            />
          ))}
        </g>

        <g className="brand-mark__ring brand-mark__ring--reverse">
          <polygon
            points={INNER_HEX}
            fill="none"
            stroke="url(#brand-ring-soft)"
            strokeWidth="0.7"
            strokeLinejoin="round"
          />
        </g>

        <circle r="1.8" cx="0" cy="0" fill="rgba(125,231,255,1)" className="brand-mark__dot" />
      </svg>
    </div>
  )
}

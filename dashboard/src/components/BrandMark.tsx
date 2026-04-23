import { useEffect, useRef } from 'react'
import { clsx } from 'clsx'

interface BrandMarkProps {
  size?: number
  className?: string
}

type Vec3 = [number, number, number]

const VERTICES: ReadonlyArray<Vec3> = [
  [0, -1, 0],
  [0, 1, 0],
  [1, 0, 0],
  [-1, 0, 0],
  [0, 0, 1],
  [0, 0, -1],
]

const FACES: ReadonlyArray<[number, number, number]> = [
  [0, 2, 4],
  [0, 4, 3],
  [0, 3, 5],
  [0, 5, 2],
  [1, 4, 2],
  [1, 3, 4],
  [1, 5, 3],
  [1, 2, 5],
]

function normalize(v: Vec3): Vec3 {
  const len = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / len, v[1] / len, v[2] / len]
}

function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

const LIGHT = normalize([-0.55, -0.92, 0.45])
const RIM = normalize([0.6, 0.2, 0.9])

export function BrandMark({ size = 40, className }: BrandMarkProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
    canvas.style.width = `${size}px`
    canvas.style.height = `${size}px`

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const cx = size / 2
    const cy = size / 2
    const scale = size * 0.34
    const projected: Array<[number, number, number]> = VERTICES.map(() => [0, 0, 0])
    let rafId = 0
    const start = performance.now()

    const render = (now: number) => {
      const t = prefersReduced ? 0 : (now - start) / 1000
      const yaw = t * 0.42
      const pitch = -0.22 + Math.sin(t * 0.33) * 0.14
      const roll = Math.sin(t * 0.21) * 0.06

      const cyaw = Math.cos(yaw)
      const syaw = Math.sin(yaw)
      const cpit = Math.cos(pitch)
      const spit = Math.sin(pitch)
      const crol = Math.cos(roll)
      const srol = Math.sin(roll)

      for (let i = 0; i < VERTICES.length; i++) {
        const [x, y, z] = VERTICES[i]
        const x1 = x * cyaw + z * syaw
        const z1 = -x * syaw + z * cyaw
        const y2 = y * cpit - z1 * spit
        const z2 = y * spit + z1 * cpit
        const x3 = x1 * crol - y2 * srol
        const y3 = x1 * srol + y2 * crol
        projected[i] = [cx + x3 * scale, cy + y3 * scale, z2]
      }

      ctx.save()
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, size, size)

      const halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.58)
      halo.addColorStop(0, 'rgba(125, 231, 255, 0.22)')
      halo.addColorStop(0.55, 'rgba(125, 231, 255, 0.05)')
      halo.addColorStop(1, 'rgba(125, 231, 255, 0)')
      ctx.fillStyle = halo
      ctx.fillRect(0, 0, size, size)

      const sorted = FACES.map((face) => {
        const a = projected[face[0]]
        const b = projected[face[1]]
        const c = projected[face[2]]
        return { face, avgZ: (a[2] + b[2] + c[2]) / 3, a, b, c }
      }).sort((p, q) => p.avgZ - q.avgZ)

      for (const { face, a, b, c } of sorted) {
        const v0 = VERTICES[face[0]]
        const v1 = VERTICES[face[1]]
        const v2 = VERTICES[face[2]]
        const rawNormal = cross(sub(v1, v0), sub(v2, v0))
        const n = normalize(rawNormal)
        const cyawN = cyaw
        const syawN = syaw
        const nx1 = n[0] * cyawN + n[2] * syawN
        const nz1 = -n[0] * syawN + n[2] * cyawN
        const ny2 = n[1] * cpit - nz1 * spit
        const nz2 = n[1] * spit + nz1 * cpit
        const nx3 = nx1 * crol - ny2 * srol
        const ny3 = nx1 * srol + ny2 * crol
        const worldNormal: Vec3 = [nx3, ny3, nz2]
        const lambert = Math.max(0, dot(worldNormal, LIGHT))
        const rim = Math.max(0, dot(worldNormal, RIM))
        const facing = Math.max(0, -worldNormal[2])

        const mid = 0.18 + lambert * 0.55 + rim * 0.18
        const litR = Math.round(14 + mid * 180)
        const litG = Math.round(28 + mid * 210)
        const litB = Math.round(52 + mid * 210)
        const fillAlpha = 0.55 + facing * 0.32

        ctx.beginPath()
        ctx.moveTo(a[0], a[1])
        ctx.lineTo(b[0], b[1])
        ctx.lineTo(c[0], c[1])
        ctx.closePath()
        ctx.fillStyle = `rgba(${litR}, ${litG}, ${litB}, ${fillAlpha.toFixed(3)})`
        ctx.fill()

        const edgeAlpha = 0.18 + lambert * 0.35 + rim * 0.25
        ctx.lineJoin = 'round'
        ctx.strokeStyle = `rgba(199, 171, 102, ${Math.min(0.85, edgeAlpha).toFixed(3)})`
        ctx.lineWidth = 0.7
        ctx.stroke()

        if (lambert > 0.72) {
          ctx.strokeStyle = `rgba(255, 248, 226, ${((lambert - 0.72) * 1.6).toFixed(3)})`
          ctx.lineWidth = 0.5
          ctx.stroke()
        }
      }

      ctx.globalCompositeOperation = 'lighter'
      const coreRadius = size * 0.26
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreRadius)
      const pulse = 0.7 + (prefersReduced ? 0 : Math.sin(t * 1.4) * 0.25)
      core.addColorStop(0, `rgba(255, 255, 255, ${(0.55 * pulse).toFixed(3)})`)
      core.addColorStop(0.35, `rgba(125, 231, 255, ${(0.45 * pulse).toFixed(3)})`)
      core.addColorStop(1, 'rgba(125, 231, 255, 0)')
      ctx.fillStyle = core
      ctx.beginPath()
      ctx.arc(cx, cy, coreRadius, 0, Math.PI * 2)
      ctx.fill()

      const specAngle = t * 0.9
      const sx = cx + Math.cos(specAngle) * size * 0.22
      const sy = cy + Math.sin(specAngle) * size * 0.22
      const spec = ctx.createRadialGradient(sx, sy, 0, sx, sy, size * 0.14)
      spec.addColorStop(0, 'rgba(255, 252, 232, 0.42)')
      spec.addColorStop(1, 'rgba(255, 252, 232, 0)')
      ctx.fillStyle = spec
      ctx.beginPath()
      ctx.arc(sx, sy, size * 0.14, 0, Math.PI * 2)
      ctx.fill()
      ctx.globalCompositeOperation = 'source-over'

      ctx.restore()

      if (!prefersReduced) {
        rafId = window.requestAnimationFrame(render)
      }
    }

    rafId = window.requestAnimationFrame(render)
    return () => window.cancelAnimationFrame(rafId)
  }, [size])

  return (
    <div
      className={clsx('brand-mark', className)}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <span className="brand-mark__plate" aria-hidden="true" />
      <canvas ref={canvasRef} className="brand-mark__canvas" />
      <span className="brand-mark__gloss" aria-hidden="true" />
    </div>
  )
}

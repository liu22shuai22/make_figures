import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import { number } from '../usage'

interface Props {
  input: number
  output: number
  inputPct: number
  outputPct: number
}

const DIE_W = 152
const DIE_D = 152
const HALF_W = DIE_W / 2
const HALF_D = DIE_D / 2
const DEG = Math.PI / 180
const H_MIN = 14
const H_MAX = 64
const H_DEFAULT = 28

type Mat4 = number[]

function multiply(a: Mat4, b: Mat4): Mat4 {
  const out = new Array(16).fill(0)
  for (let column = 0; column < 4; column += 1) {
    for (let row = 0; row < 4; row += 1) {
      out[column * 4 + row] =
        a[row] * b[column * 4] +
        a[4 + row] * b[column * 4 + 1] +
        a[8 + row] * b[column * 4 + 2] +
        a[12 + row] * b[column * 4 + 3]
    }
  }
  return out
}

function rotateX(degrees: number): Mat4 {
  const c = Math.cos(degrees * DEG)
  const s = Math.sin(degrees * DEG)
  return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]
}

function rotateY(degrees: number): Mat4 {
  const c = Math.cos(degrees * DEG)
  const s = Math.sin(degrees * DEG)
  return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]
}

function cssMatrix(matrix: Mat4): string {
  return `matrix3d(${matrix.join(',')})`
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function transistorsOf(tokens: number) {
  const raw = Math.max(0, tokens) * 12_000
  if (raw >= 1e8) return `${(raw / 1e8).toFixed(1).replace(/\.0$/, '')} 亿`
  if (raw >= 1e4) return `${Math.round(raw / 1e4)} 万`
  return number(Math.round(raw))
}

/**
 * 用量芯片 die：多层互连纹理、焊盘环、功能岛；拖转 + 滚轮调厚。
 */
export default function UsageVolume({ input, output, inputPct, outputPct }: Props) {
  const matrix = useRef(multiply(rotateY(-24), rotateX(-62)))
  const velocity = useRef({ x: 0, y: 0 })
  const [transform, setTransform] = useState(() => cssMatrix(matrix.current))
  const drag = useRef<{ x: number; y: number; base: Mat4; t: number } | null>(null)
  const [active, setActive] = useState(false)
  const still = useRef(false)
  const stageRef = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState(H_DEFAULT)

  const totalTx = transistorsOf(input + output)
  const inShare = Math.max(inputPct, input > 0 ? 8 : 0)
  const outShare = input > 0 || output > 0 ? Math.max(100 - inShare, output > 0 ? 8 : 0) : 0

  useEffect(() => {
    still.current = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }, [])

  useEffect(() => {
    const stage = stageRef.current
    if (!stage) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const step = event.deltaY > 0 ? -2 : event.deltaY < 0 ? 2 : 0
      if (step === 0) return
      setHeight((current) => clamp(current + step, H_MIN, H_MAX))
    }
    stage.addEventListener('wheel', onWheel, { passive: false })
    return () => stage.removeEventListener('wheel', onWheel)
  }, [])

  const commit = (next: Mat4) => {
    matrix.current = next
    setTransform(cssMatrix(next))
  }

  useEffect(() => {
    if (still.current) return
    if (active) return
    let frame = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = Math.min(32, now - last)
      last = now
      const vx = velocity.current.x
      const vy = velocity.current.y
      if (Math.abs(vx) > 0.02 || Math.abs(vy) > 0.02) {
        commit(multiply(rotateY(vx * dt), multiply(rotateX(vy * dt), matrix.current)))
        velocity.current.x *= Math.pow(0.93, dt / 16)
        velocity.current.y *= Math.pow(0.93, dt / 16)
      } else {
        velocity.current.x = 0
        velocity.current.y = 0
        commit(multiply(rotateY(dt * 0.005), matrix.current))
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [active])

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    velocity.current = { x: 0, y: 0 }
    drag.current = { x: event.clientX, y: event.clientY, base: matrix.current, t: performance.now() }
    setActive(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    const now = performance.now()
    const dx = event.clientX - drag.current.x
    const dy = event.clientY - drag.current.y
    const dt = Math.max(8, now - drag.current.t)
    velocity.current = { x: (dx * 0.42) / dt, y: (-dy * 0.42) / dt }
    commit(multiply(rotateY(dx * 0.42), multiply(rotateX(-dy * 0.42), drag.current.base)))
    drag.current = { x: event.clientX, y: event.clientY, base: matrix.current, t: now }
  }

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    setActive(false)
    try {
      event.currentTarget.releasePointerCapture(event.pointerId)
    } catch {
      // ignore
    }
  }

  const nudge = (rx: number, ry: number) => {
    velocity.current = { x: 0, y: 0 }
    commit(multiply(rotateY(ry), multiply(rotateX(rx), matrix.current)))
  }

  return (
    <div className="usage-volume is-chip" data-testid="usage-volume">
      <div
        ref={stageRef}
        className={'vol-stage' + (active ? ' is-active' : '')}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        role="img"
        aria-label={`今日用量芯片：输入 ${number(input)}（${inputPct}%），输出 ${number(output)}（${outputPct}%），示意约 ${totalTx} 晶体管。拖转旋转，滚轮调节厚度。`}
        tabIndex={0}
        onKeyDown={(event) => {
          const step = event.shiftKey ? 18 : 12
          if (event.key === 'ArrowLeft') { event.preventDefault(); nudge(0, -step) }
          if (event.key === 'ArrowRight') { event.preventDefault(); nudge(0, step) }
          if (event.key === 'ArrowUp') { event.preventDefault(); nudge(step, 0) }
          if (event.key === 'ArrowDown') { event.preventDefault(); nudge(-step, 0) }
          if (event.key === '+' || event.key === '=') {
            event.preventDefault()
            setHeight((current) => clamp(current + 2, H_MIN, H_MAX))
          }
          if (event.key === '-' || event.key === '_') {
            event.preventDefault()
            setHeight((current) => clamp(current - 2, H_MIN, H_MAX))
          }
        }}
      >
        <div className="vol-ambiance vol-ambiance-chip" aria-hidden="true" />
        <div className="vol-floor" aria-hidden="true" />
        <div className="vol-floor vol-floor-ring" aria-hidden="true" />

        <div
          className="vol-turn"
          style={{
            transform,
            width: DIE_W,
            height,
            marginLeft: -HALF_W,
            marginTop: -height / 2,
          }}
        >
          <div
            className="vol-package"
            style={{
              ['--vol-h' as string]: '12px',
              ['--vol-half-w' as string]: `${HALF_W + 12}px`,
              ['--vol-half-d' as string]: `${HALF_D + 12}px`,
              width: DIE_W + 24,
              height: 12,
              marginLeft: -12,
              top: height - 1,
            }}
            aria-hidden="true"
          >
            <i className="vol-face vol-front" />
            <i className="vol-face vol-back" />
            <i className="vol-face vol-left" />
            <i className="vol-face vol-right" />
            <i className="vol-face vol-top">
              <b className="vol-pkg-lid" />
            </i>
            <i className="vol-face vol-bottom">
              <span className="vol-bga" aria-hidden="true">
                {Array.from({ length: 64 }, (_, index) => <b key={index} />)}
              </span>
            </i>
          </div>

          <div
            className="vol-die-body"
            style={{
              height,
              ['--vol-h' as string]: `${height}px`,
              ['--vol-half-w' as string]: `${HALF_W}px`,
              ['--vol-half-d' as string]: `${HALF_D}px`,
              ['--in-share' as string]: `${inShare}%`,
              ['--out-share' as string]: `${outShare}%`,
            }}
          >
            <i className="vol-face vol-front">
              <b className="vol-gates" />
              <b className="vol-metal" />
              <b className="vol-bevel" />
              <span className="vol-edge-stripes" />
            </i>
            <i className="vol-face vol-back">
              <b className="vol-gates" />
              <b className="vol-bevel" />
            </i>
            <i className="vol-face vol-left">
              <b className="vol-gates" />
              <b className="vol-bevel" />
              <span className="vol-edge-stripes" />
            </i>
            <i className="vol-face vol-right">
              <b className="vol-gates" />
              <b className="vol-bevel" />
              <span className="vol-edge-stripes" />
            </i>

            <i className="vol-face vol-top vol-die-shot">
              <b className="vol-region vol-region-in" />
              <b className="vol-region vol-region-out" />
              <b className="vol-gates vol-gates-nano" />
              <b className="vol-gates vol-gates-dense" />
              <b className="vol-metal vol-metal-dense" />
              <b className="vol-bus" />
              <b className="vol-seal" />
              <b className="vol-specular" />
              <span className="vol-blocks" aria-hidden="true">
                <b className="blk-a"><i /></b>
                <b className="blk-b"><i /></b>
                <b className="blk-c"><i /></b>
                <b className="blk-d"><i /></b>
                <b className="blk-e"><i /></b>
                <b className="blk-f"><i /></b>
              </span>
              <span className="vol-pads" aria-hidden="true">
                {Array.from({ length: 44 }, (_, index) => <b key={index} />)}
              </span>
              <b className="vol-bevel" />
              <span className="vol-die-mark">
                <strong>DIE</strong>
                <em>{totalTx}</em>
                <small>示意晶体管</small>
              </span>
            </i>

            <i className="vol-face vol-bottom">
              <b className="vol-bevel" />
            </i>
          </div>
        </div>
      </div>

      <div className="vol-readout">
        <span className="vol-readout-in">
          <i aria-hidden="true" />
          <span className="vol-readout-copy">
            <strong>输入</strong>
            <b>{number(input)}</b>
            <small>{inputPct}% · {transistorsOf(input)}</small>
          </span>
        </span>
        <span className="vol-readout-out">
          <i aria-hidden="true" />
          <span className="vol-readout-copy">
            <strong>输出</strong>
            <b>{number(output)}</b>
            <small>{outputPct}% · {transistorsOf(output)}</small>
          </span>
        </span>
      </div>

      <p className="vol-hint">
        {active ? '检视中' : '拖转检视 · 滚轮调厚度'}
      </p>
    </div>
  )
}

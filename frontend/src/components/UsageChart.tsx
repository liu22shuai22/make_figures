import { useEffect, useRef, useState } from 'react'
import { compact, niceMax, number, type UsageDay } from '../usage'

interface Props {
  series: UsageDay[]
  height?: number
}

const PAD = { top: 24, right: 18, bottom: 28, left: 52 }
const DEPTH_X = 11
const DEPTH_Y = 8

/** 手写 SVG 立体堆叠柱：正面 + 顶面 + 侧面，下层输入、上层输出 */
export default function UsageChart({ series, height = 288 }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const element = host.current
    if (!element) return
    setWidth(Math.round(element.clientWidth))
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0].contentRect.width)
      setWidth((current) => (current === next ? current : next))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const plotWidth = Math.max(width - PAD.left - PAD.right, 24)
  const plotHeight = height - PAD.top - PAD.bottom
  const baseline = PAD.top + plotHeight
  const slot = plotWidth / Math.max(series.length, 1)
  const barWidth = Math.max(4, Math.min(26, slot * 0.5))

  const max = Math.max(...series.map((day) => day.input_tokens + day.output_tokens), 0)
  const ceiling = niceMax(max)
  const scale = (value: number) => (value / ceiling) * plotHeight

  const ticks = [0, 0.5, 1].map((ratio) => ({
    value: ceiling * ratio,
    y: baseline - scale(ceiling * ratio),
  }))

  const labelIndexes = new Set([0, Math.floor(series.length / 3), Math.floor((series.length * 2) / 3), series.length - 1])

  return (
    <div className="chart-host" ref={host}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`最近 ${series.length} 天已确认 Token 趋势，输入与输出立体堆叠`}
        >
          {ticks.map((tick) => (
            <g key={tick.value}>
              <line className="chart-grid-line" x1={PAD.left} x2={width - PAD.right} y1={tick.y} y2={tick.y} />
              <text className="chart-tick" x={PAD.left - 10} y={tick.y + 4} textAnchor="end">
                {compact(tick.value)}
              </text>
            </g>
          ))}

          {series.map((day, index) => {
            const center = PAD.left + slot * index + slot / 2
            const x = center - barWidth / 2
            const inputHeight = scale(day.input_tokens)
            const outputHeight = scale(day.output_tokens)
            const stacked = inputHeight + outputHeight
            const gap = inputHeight > 0 && outputHeight > 0 ? 1.5 : 0
            const inputY = baseline - inputHeight
            const outputY = baseline - stacked
            const inputFace = Math.max(inputHeight - gap, 0)
            const outputFace = Math.max(outputHeight, 0)

            const tooltip = [
              `${day.day}${day.isToday ? '（今天）' : ''}`,
              `输入 ${number(day.input_tokens)}`,
              `输出 ${number(day.output_tokens)}`,
              `${number(day.calls)} 次请求`,
              day.unreported_calls > 0 ? `${number(day.unreported_calls)} 次用量未返回` : '',
            ]
              .filter(Boolean)
              .join(' · ')

            return (
              <g className="chart-col" key={day.day}>
                {day.isToday && (
                  <rect
                    className="chart-today"
                    x={PAD.left + slot * index + 1}
                    y={PAD.top - 4}
                    width={Math.max(slot - 2, 1)}
                    height={plotHeight + 4}
                    rx={8}
                  />
                )}
                <rect
                  className="chart-hit"
                  x={PAD.left + slot * index}
                  y={PAD.top - 4}
                  width={slot}
                  height={plotHeight + 4}
                >
                  <title>{tooltip}</title>
                </rect>

                {inputFace > 0.8 && (
                  <BarBlock
                    className="in"
                    x={x}
                    y={inputY + (gap > 0 ? gap : 0)}
                    width={barWidth}
                    height={inputFace}
                    roundedTop={outputFace <= 0}
                  />
                )}

                {outputFace > 0.8 && (
                  <BarBlock
                    className="out"
                    x={x}
                    y={outputY}
                    width={barWidth}
                    height={outputFace}
                    roundedTop
                  />
                )}

                {day.unreported_calls > 0 && (
                  <rect
                    className="chart-missing"
                    x={x}
                    y={(stacked > 0 ? outputY : baseline) - 10}
                    width={barWidth}
                    height={6}
                    rx={1.5}
                  />
                )}

                {labelIndexes.has(index) && (
                  <text
                    className={day.isToday ? 'chart-x chart-x-today' : 'chart-x'}
                    x={center}
                    y={baseline + 18}
                    textAnchor="middle"
                  >
                    {day.isToday ? '今天' : day.label}
                  </text>
                )}
              </g>
            )
          })}

          <line className="chart-axis-line" x1={PAD.left} x2={width - PAD.right} y1={baseline} y2={baseline} />
        </svg>
      )}
    </div>
  )
}

/** 一根有厚度的柱：侧面 → 正面 → 顶面，保证叠放顺序正确 */
function BarBlock({
  className,
  x,
  y,
  width,
  height,
  roundedTop,
}: {
  className: 'in' | 'out'
  x: number
  y: number
  width: number
  height: number
  roundedTop: boolean
}) {
  const top = y
  const bottom = y + height
  const right = x + width
  const dx = DEPTH_X
  const dy = DEPTH_Y

  const side = [
    `M${right} ${top}`,
    `L${right + dx} ${top - dy}`,
    `L${right + dx} ${bottom - dy}`,
    `L${right} ${bottom}`,
    'Z',
  ].join(' ')

  const lid = [
    `M${x} ${top}`,
    `L${x + dx} ${top - dy}`,
    `L${right + dx} ${top - dy}`,
    `L${right} ${top}`,
    'Z',
  ].join(' ')

  return (
    <g className={'chart-block chart-block-' + className}>
      <path className="chart-block-side" d={side} />
      <rect
        className="chart-block-face"
        x={x}
        y={top}
        width={width}
        height={height}
        rx={roundedTop ? 2.5 : 0}
        ry={roundedTop ? 2.5 : 0}
      />
      {roundedTop && <path className="chart-block-top" d={lid} />}
      {!roundedTop && <path className="chart-block-top is-flat" d={lid} />}
    </g>
  )
}

import { useEffect, useMemo, useState } from 'react'
import ThemeToggle from './components/ThemeToggle'
import BrandMark from './components/BrandMark'
import UsageChart from './components/UsageChart'
import UsageVolume from './components/UsageVolume'
import type { Theme } from './theme'
import { buildSeries, clockTime, number, tokens, type Usage } from './usage'

interface Props {
  onBack: () => void
  theme: Theme
  onToggleTheme: () => void
}

const WINDOW_DAYS = 30

function splitPercent(input: number, output: number) {
  const whole = input + output
  if (whole <= 0) return null
  const inputPct = Math.round((input / whole) * 100)
  return { inputPct, outputPct: 100 - inputPct }
}

function usageStory(usage: Usage, series: ReturnType<typeof buildSeries>) {
  const todayTotal = tokens(usage.today)
  const all = tokens(usage.total)
  if (all <= 0 || todayTotal <= 0) return null
  const share = Math.max(1, Math.round((todayTotal / all) * 100))
  const peak = Math.max(...series.map((day) => tokens(day)))
  if (todayTotal >= peak) return `今天是近 ${WINDOW_DAYS} 天的高峰，约占累计的 ${share}%`
  return `今天约占累计已确认用量的 ${share}%`
}

export default function TokenUsage({ onBack, theme, onToggleTheme }: Props) {
  const [usage, setUsage] = useState<Usage>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [updatedAt, setUpdatedAt] = useState<Date>()

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    void (async () => {
      try {
        const response = await fetch('/api/usage', { signal: controller.signal, cache: 'no-store' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const data: Usage = await response.json()
        if (controller.signal.aborted) return
        setUsage(data)
        setUpdatedAt(new Date())
      } catch {
        if (!controller.signal.aborted) setError(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [refresh])

  const series = useMemo(
    () => (usage ? buildSeries(usage.daily, usage.today.day, WINDOW_DAYS) : []),
    [usage],
  )

  const unreported = usage?.total.unreported_calls ?? 0
  const hasCalls = (usage?.total.calls ?? 0) > 0
  const seriesUnreported = series.some((day) => day.unreported_calls > 0)
  const todaySplit = usage ? splitPercent(usage.today.input_tokens, usage.today.output_tokens) : null
  const totalSplit = usage ? splitPercent(usage.total.input_tokens, usage.total.output_tokens) : null
  const story = usage ? usageStory(usage, series) : null
  const todayShareOfTotal = usage && tokens(usage.total) > 0
    ? Math.min(100, Math.round((tokens(usage.today) / tokens(usage.total)) * 100))
    : 0

  return (
    <div className="app">
      <header className="topbar usage-topbar">
        <div className="brand">
          <BrandMark />
          <div className="brand-text"><h1>Token 用量</h1></div>
        </div>
        <div className="toolbar">
          <button type="button" className="btn" onClick={onBack} data-testid="usage-back">返回工作台</button>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>

      <main className="usage-page" aria-busy={loading}>
        <div className="usage-bar">
          <p className="usage-scope">
            本机后端的模型调用，按服务器日期归档，含重试与分批补全。
          </p>
          <div className="usage-actions">
            {updatedAt && (
              <span className="usage-stamp">{clockTime(updatedAt)} 更新</span>
            )}
            <button
              type="button"
              className="usage-refresh"
              disabled={loading}
              onClick={() => setRefresh((value) => value + 1)}
              data-testid="usage-refresh"
            >
              {loading ? '读取中…' : '刷新'}
            </button>
          </div>
        </div>

        {error && usage && (
          <p className="usage-banner" role="alert" data-testid="usage-stale">
            刷新失败，以下仍为 {updatedAt ? clockTime(updatedAt) : '上次'} 读取的用量。
          </p>
        )}

        {!usage && loading && <UsageSkeleton />}

        {!usage && !loading && error && (
          <div className="usage-error" role="alert" data-testid="usage-error">
            <strong>无法读取用量</strong>
            <p>请确认本机 ERFlow 后端已启动，然后重试。已记录的数据不会丢失。</p>
            <button type="button" className="btn" onClick={() => setRefresh((value) => value + 1)}>
              重试
            </button>
          </div>
        )}

        {usage && (
          <>
            {story && (
              <p className="usage-insight" data-testid="usage-insight">
                <span className="usage-insight-mark" aria-hidden="true" />
                {story}
              </p>
            )}

            <section className="usage-overview" aria-label="用量概览">
              <article className="usage-slate usage-today" data-testid="usage-today">
                <div className="usage-slate-main">
                  <p className="usage-label">今日已确认</p>
                  <p className="usage-value">
                    <CountUp value={tokens(usage.today)} />
                  </p>
                  <p className="usage-split">
                    <span><i className="usage-dot" aria-hidden="true" />输入 <b>{number(usage.today.input_tokens)}</b>{todaySplit && <em>{todaySplit.inputPct}%</em>}</span>
                    <span><i className="usage-dot usage-dot-out" aria-hidden="true" />输出 <b>{number(usage.today.output_tokens)}</b>{todaySplit && <em>{todaySplit.outputPct}%</em>}</span>
                  </p>
                  <p className="usage-meta">
                    {usage.today.calls > 0 ? `${number(usage.today.calls)} 次请求` : '今天还没有请求'}
                    {usage.today.unreported_calls > 0 && (
                      <> · 其中 <b>{number(usage.today.unreported_calls)}</b> 次用量未返回</>
                    )}
                  </p>
                </div>
              </article>

              <div className="usage-stage">
                {todaySplit ? (
                  <UsageVolume
                    input={usage.today.input_tokens}
                    output={usage.today.output_tokens}
                    inputPct={todaySplit.inputPct}
                    outputPct={todaySplit.outputPct}
                  />
                ) : (
                  <div className="usage-stage-empty">
                    <p>今天还没有已确认用量</p>
                  </div>
                )}
              </div>

              <article className="usage-slate usage-total" data-testid="usage-total">
                <div className="usage-slate-main">
                  <p className="usage-label">累计已确认</p>
                  <p className="usage-value">
                    <CountUp value={tokens(usage.total)} />
                  </p>
                  <p className="usage-split">
                    <span><i className="usage-dot" aria-hidden="true" />输入 <b>{number(usage.total.input_tokens)}</b>{totalSplit && <em>{totalSplit.inputPct}%</em>}</span>
                    <span><i className="usage-dot usage-dot-out" aria-hidden="true" />输出 <b>{number(usage.total.output_tokens)}</b>{totalSplit && <em>{totalSplit.outputPct}%</em>}</span>
                  </p>
                  <p className="usage-meta">
                    {number(usage.total.calls)} 次请求
                    {unreported > 0 && <> · 其中 <b>{number(unreported)}</b> 次用量未返回</>}
                  </p>
                  {tokens(usage.total) > 0 && (
                    <div className="usage-share-line" aria-label={`今日约占累计 ${todayShareOfTotal}%`}>
                      <span>今日占累计</span>
                      <span className="usage-share-track">
                        <i style={{ width: `${Math.max(todayShareOfTotal, todayShareOfTotal > 0 ? 2 : 0)}%` }} />
                      </span>
                      <b>{todayShareOfTotal}%</b>
                    </div>
                  )}
                </div>
                {totalSplit && (
                  <ShareRing
                    inputPct={totalSplit.inputPct}
                    outputPct={totalSplit.outputPct}
                    caption="累计构成"
                    size="md"
                  />
                )}
              </article>

              {unreported > 0 && (
                <p className="usage-footnote">
                  合计只累加模型已返回的用量。未返回的请求记为「未确认」，不计入合计，也不估算费用。
                </p>
              )}
            </section>

            <section className="usage-section" aria-labelledby="usage-trend-title">
              <div className="usage-section-head">
                <div>
                  <h2 id="usage-trend-title">最近 {WINDOW_DAYS} 天</h2>
                  <p className="usage-story">柱体带厚度：下层输入、上层输出。</p>
                </div>
                {hasCalls && (
                  <div className="usage-legend">
                    <span><i className="legend-swatch legend-in" aria-hidden="true" />输入</span>
                    <span><i className="legend-swatch legend-out" aria-hidden="true" />输出</span>
                    {seriesUnreported && (
                      <span><i className="legend-swatch legend-missing" aria-hidden="true" />用量未返回</span>
                    )}
                  </div>
                )}
              </div>

              {hasCalls ? (
                <UsageChart series={series} />
              ) : (
                <div className="usage-empty" data-testid="usage-empty">
                  <strong>最近 {WINDOW_DAYS} 天还没有用量记录</strong>
                  <p>在「工作台」用一段中文描述生成一次 E-R 图，当天的输入与输出 Token 会出现在这里。</p>
                </div>
              )}
            </section>

            {usage.daily.length > 0 && (
              <section className="usage-section" aria-labelledby="usage-detail-title">
                <div className="usage-section-head">
                  <h2 id="usage-detail-title">每日明细</h2>
                  <span className="usage-hint">
                    <span className="usage-hint-wide">按日期倒序 · 仅含已确认用量</span>
                    <span className="usage-hint-narrow">左右滑动看全部列</span>
                  </span>
                </div>
                <div className="usage-table-wrap">
                  <table className="usage-table">
                    <thead>
                      <tr>
                        <th scope="col">日期</th>
                        <th scope="col">输入</th>
                        <th scope="col">输出</th>
                        <th scope="col">合计</th>
                        <th scope="col">请求</th>
                        <th scope="col">用量未返回</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.daily.map((day) => (
                        <tr key={day.day} className={day.day === usage.today.day ? 'is-today' : undefined}>
                          <th scope="row">
                            {day.day}
                            {day.day === usage.today.day && <span className="usage-today-tag">今天</span>}
                          </th>
                          <td>{number(day.input_tokens)}</td>
                          <td>{number(day.output_tokens)}</td>
                          <td className="is-strong">{number(tokens(day))}</td>
                          <td>{number(day.calls)}</td>
                          <td className={day.unreported_calls > 0 ? 'is-warn' : 'is-dim'}>
                            {number(day.unreported_calls)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </>
        )}
      </main>
    </div>
  )
}

/** 输入/输出环形占比：一眼看出构成，而不是一条扁进度条 */
function ShareRing({
  inputPct,
  outputPct,
  caption,
  size = 'lg',
}: {
  inputPct: number
  outputPct: number
  caption: string
  size?: 'lg' | 'md'
}) {
  const dim = size === 'lg' ? 118 : 92
  const stroke = size === 'lg' ? 12 : 10
  const radius = (dim - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const inputLen = (inputPct / 100) * circumference
  const outputLen = (outputPct / 100) * circumference
  const gap = inputPct > 0 && outputPct > 0 ? 3 : 0

  return (
    <div
      className={'usage-ring usage-ring-' + size}
      role="img"
      aria-label={`${caption}：输入 ${inputPct}%，输出 ${outputPct}%`}
    >
      <svg width={dim} height={dim} viewBox={`0 0 ${dim} ${dim}`} aria-hidden="true">
        <circle
          className="usage-ring-track"
          cx={dim / 2}
          cy={dim / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
        />
        {inputPct > 0 && (
          <circle
            className="usage-ring-in"
            cx={dim / 2}
            cy={dim / 2}
            r={radius}
            fill="none"
            strokeWidth={stroke}
            strokeDasharray={`${Math.max(inputLen - gap, 1)} ${circumference}`}
            strokeDashoffset={0}
            strokeLinecap="butt"
            transform={`rotate(-90 ${dim / 2} ${dim / 2})`}
          />
        )}
        {outputPct > 0 && (
          <circle
            className="usage-ring-out"
            cx={dim / 2}
            cy={dim / 2}
            r={radius}
            fill="none"
            strokeWidth={stroke}
            strokeDasharray={`${Math.max(outputLen - gap, 1)} ${circumference}`}
            strokeDashoffset={-(inputLen + (inputPct > 0 ? gap : 0))}
            strokeLinecap="butt"
            transform={`rotate(-90 ${dim / 2} ${dim / 2})`}
          />
        )}
      </svg>
      <div className="usage-ring-core">
        <strong>{inputPct}<small>%</small></strong>
        <span>输入</span>
      </div>
    </div>
  )
}

/** 数字入场：从 0 滚到目标值，减少动效时直接到位 */
function CountUp({ value }: { value: number }) {
  const [display, setDisplay] = useState(0)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setDisplay(value)
      return
    }
    const start = performance.now()
    const from = 0
    const duration = Math.min(900, 420 + Math.log10(Math.max(value, 1)) * 180)
    let frame = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - (1 - t) ** 3
      setDisplay(Math.round(from + (value - from) * eased))
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])

  return <>{number(display)}</>
}

function UsageSkeleton() {
  return (
    <div className="usage-skeleton" aria-hidden="true">
      <div className="sk-cards">
        <div className="sk-card" />
        <div className="sk-card" />
      </div>
      <div className="sk-block" />
    </div>
  )
}

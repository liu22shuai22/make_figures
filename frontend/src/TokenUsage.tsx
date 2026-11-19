import { useEffect, useMemo, useState } from 'react'
import BrandMark from './components/BrandMark'
import UsageChart from './components/UsageChart'
import UsageVolume from './components/UsageVolume'
import { buildSeries, clockTime, number, tokens, type Usage, type UsageChannel } from './usage'
import { useLocale } from './LocaleContext'
import type { AppCopy } from './appLocale'

interface Props {
  onBack: () => void
}

const WINDOW_DAYS = 30

function splitPercent(input: number, output: number) {
  const whole = input + output
  if (whole <= 0) return null
  const inputPct = Math.round((input / whole) * 100)
  return { inputPct, outputPct: 100 - inputPct }
}

function usageStory(usage: Usage, series: ReturnType<typeof buildSeries>, u: AppCopy['usage']) {
  const todayTotal = tokens(usage.today)
  const all = tokens(usage.total)
  if (all <= 0 || todayTotal <= 0) return null
  const share = Math.max(1, Math.round((todayTotal / all) * 100))
  const peak = Math.max(...series.map((day) => tokens(day)))
  if (todayTotal >= peak) return u.peakStory(WINDOW_DAYS, share)
  return u.shareStory(share)
}

export default function TokenUsage({ onBack }: Props) {
  const { app } = useLocale()
  const u = app.usage
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
  const story = usage ? usageStory(usage, series, u) : null
  const todayShareOfTotal = usage && tokens(usage.total) > 0
    ? Math.min(100, Math.round((tokens(usage.today) / tokens(usage.total)) * 100))
    : 0
  const channels = [...(usage?.channels ?? [])].sort((a, b) => {
    // Keep providers above the pre-upgrade bucket even if the API order changes.
    const legacyRank = (id: string) => (id === '_legacy' ? 1 : 0)
    const rank = legacyRank(a.id) - legacyRank(b.id)
    if (rank !== 0) return rank
    return tokens(b) - tokens(a)
  })
  // Share bars compare within the channel list (same 30-day window), not lifetime total.
  const channelWindowTokens = channels.reduce((sum, item) => sum + tokens(item), 0)
  const hasLegacy = channels.some((item) => item.id === '_legacy')
  const hasProviderSplit = channels.some((item) => item.id !== '_legacy')

  return (
    <div className="app">
      <header className="topbar usage-topbar">
        <div className="brand">
          <BrandMark />
          <div className="brand-text"><h1>{u.title}</h1></div>
        </div>
        <div className="toolbar">
          <button type="button" className="btn" onClick={onBack} data-testid="usage-back">{app.backWorkbench}</button>
        </div>
      </header>

      <main className="usage-page" aria-busy={loading}>
        <div className="usage-bar">
          <p className="usage-scope">{u.lead}</p>
          <div className="usage-actions">
            {updatedAt && (
              <span className="usage-stamp">{u.updated(clockTime(updatedAt))}</span>
            )}
            <button
              type="button"
              className="usage-refresh"
              disabled={loading}
              onClick={() => setRefresh((value) => value + 1)}
              data-testid="usage-refresh"
            >
              {loading ? u.reading : u.refresh}
            </button>
          </div>
        </div>

        {error && usage && (
          <p className="usage-banner" role="alert" data-testid="usage-stale">
            {u.refreshFail(updatedAt ? clockTime(updatedAt) : u.last)}
          </p>
        )}

        {!usage && loading && <UsageSkeleton />}

        {!usage && !loading && error && (
          <div className="usage-error" role="alert" data-testid="usage-error">
            <strong>{u.readFail}</strong>
            <p>{u.readFailHint}</p>
            <button type="button" className="btn" onClick={() => setRefresh((value) => value + 1)}>
              {u.retry}
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

            <section className="usage-overview" aria-label={u.overview}>
              <article className="usage-slate usage-today" data-testid="usage-today">
                <div className="usage-slate-main">
                  <p className="usage-label">{u.todayConfirmed}</p>
                  <p className="usage-value">
                    <CountUp value={tokens(usage.today)} />
                  </p>
                  <p className="usage-split">
                    <span><i className="usage-dot" aria-hidden="true" />{u.input} <b>{number(usage.today.input_tokens)}</b>{todaySplit && <em>{todaySplit.inputPct}%</em>}</span>
                    <span><i className="usage-dot usage-dot-out" aria-hidden="true" />{u.output} <b>{number(usage.today.output_tokens)}</b>{todaySplit && <em>{todaySplit.outputPct}%</em>}</span>
                  </p>
                  <p className="usage-meta">
                    {usage.today.calls > 0 ? u.calls(number(usage.today.calls)) : u.noCallsToday}
                    {usage.today.unreported_calls > 0 && u.unreported(number(usage.today.unreported_calls))}
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
                    <p>{u.noToday}</p>
                  </div>
                )}
              </div>

              <article className="usage-slate usage-total" data-testid="usage-total">
                <div className="usage-slate-main">
                  <p className="usage-label">{u.totalConfirmed}</p>
                  <p className="usage-value">
                    <CountUp value={tokens(usage.total)} />
                  </p>
                  <p className="usage-split">
                    <span><i className="usage-dot" aria-hidden="true" />{u.input} <b>{number(usage.total.input_tokens)}</b>{totalSplit && <em>{totalSplit.inputPct}%</em>}</span>
                    <span><i className="usage-dot usage-dot-out" aria-hidden="true" />{u.output} <b>{number(usage.total.output_tokens)}</b>{totalSplit && <em>{totalSplit.outputPct}%</em>}</span>
                  </p>
                  <p className="usage-meta">
                    {u.calls(number(usage.total.calls))}
                    {unreported > 0 && u.unreported(number(unreported))}
                  </p>
                  {tokens(usage.total) > 0 && (
                    <div className="usage-share-line" aria-label={u.todayShareAria(todayShareOfTotal)}>
                      <span>{u.todayShare}</span>
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
                    caption={u.totalComposition}
                    inputLabel={u.input}
                    ringAria={u.ringAria}
                    size="md"
                  />
                )}
              </article>

              {unreported > 0 && (
                <p className="usage-footnote">
                  {u.note}
                </p>
              )}
            </section>

            {hasCalls && (
              <section
                className={'usage-section usage-channel-section' + (hasProviderSplit ? ' is-split' : '')}
                aria-labelledby="usage-channel-title"
              >
                <div className="usage-section-head">
                  <div>
                    <h2 id="usage-channel-title">{u.byChannel}</h2>
                    <p className="usage-story">
                      {hasProviderSplit ? u.splitReady + ' · ' + u.byChannelHint : u.byChannelHint}
                    </p>
                  </div>
                </div>
                {hasLegacy && (
                  <p className="usage-channel-note" data-testid="usage-legacy-note">
                    {u.legacyHint}
                  </p>
                )}
                <div className="usage-channel-list" data-testid="usage-channels">
                  {channels.map((channel) => (
                    <ChannelCard
                      key={channel.id}
                      channel={channel}
                      totalTokens={channelWindowTokens}
                      copy={u}
                    />
                  ))}
                </div>
              </section>
            )}

            <section className="usage-section" aria-labelledby="usage-trend-title">
              <div className="usage-section-head">
                <div>
                  <h2 id="usage-trend-title">{u.recent(WINDOW_DAYS)}</h2>
                  <p className="usage-story">{u.story}</p>
                </div>
                {hasCalls && (
                  <div className="usage-legend">
                    <span><i className="legend-swatch legend-in" aria-hidden="true" />{u.input}</span>
                    <span><i className="legend-swatch legend-out" aria-hidden="true" />{u.output}</span>
                    {seriesUnreported && (
                      <span><i className="legend-swatch legend-missing" aria-hidden="true" />{u.missing}</span>
                    )}
                  </div>
                )}
              </div>

              {hasCalls ? (
                <UsageChart series={series} />
              ) : (
                <div className="usage-empty" data-testid="usage-empty">
                  <strong>{u.emptyRecent(WINDOW_DAYS)}</strong>
                  <p>{u.emptyHint}</p>
                </div>
              )}
            </section>

            {usage.daily.length > 0 && (
              <section className="usage-section" aria-labelledby="usage-detail-title">
                <div className="usage-section-head">
                  <h2 id="usage-detail-title">{u.daily}</h2>
                  <span className="usage-hint">
                    <span className="usage-hint-wide">{u.wideHint}</span>
                    <span className="usage-hint-narrow">{u.narrowHint}</span>
                  </span>
                </div>
                <div className="usage-table-wrap">
                  <table className="usage-table">
                    <thead>
                      <tr>
                        <th scope="col">{u.date}</th>
                        <th scope="col">{u.input}</th>
                        <th scope="col">{u.output}</th>
                        <th scope="col">{u.total}</th>
                        <th scope="col">{u.requests}</th>
                        <th scope="col">{u.missing}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.daily.map((day) => (
                        <tr key={day.day} className={day.day === usage.today.day ? 'is-today' : undefined}>
                          <th scope="row">
                            {day.day}
                            {day.day === usage.today.day && <span className="usage-today-tag">{u.today}</span>}
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

function ChannelCard({
  channel,
  totalTokens,
  copy,
}: {
  channel: UsageChannel
  totalTokens: number
  copy: AppCopy['usage']
}) {
  const amount = tokens(channel)
  const sharePct = totalTokens > 0 ? (amount / totalTokens) * 100 : 0
  const shareLabel =
    totalTokens <= 0 || amount <= 0
      ? ''
      : sharePct < 1
        ? `<1% ${copy.channelShare}`
        : `${Math.min(100, Math.round(sharePct))}% ${copy.channelShare}`
  const barWidth = totalTokens > 0 ? Math.max(sharePct, amount > 0 ? 2 : 0) : 0
  const models = (channel.models ?? []).filter((item) => item.model || tokens(item) > 0 || item.calls > 0)

  const legacy = channel.id === '_legacy'
  return (
    <article className={'usage-channel-card' + (legacy ? ' is-legacy' : '')}>
      <header className="usage-channel-head">
        <div>
          <p className="usage-label">{copy.channel}</p>
          <strong>{legacy ? copy.legacyChannel : channel.name}</strong>
          {!legacy && channel.id && channel.id !== channel.name && (
            <span className="usage-channel-id">{channel.id}</span>
          )}
        </div>
        <div className="usage-channel-stats">
          <b>{number(amount)}</b>
          <span>
            {copy.calls(number(channel.calls))}
            {shareLabel ? ` · ${shareLabel}` : ''}
          </span>
        </div>
      </header>
      <div className="usage-channel-bar" aria-hidden="true">
        <i style={{ width: `${Math.min(100, barWidth)}%` }} />
      </div>
      <p className="usage-split">
        <span>
          <i className="usage-dot" aria-hidden="true" />
          {copy.input} <b>{number(channel.input_tokens)}</b>
        </span>
        <span>
          <i className="usage-dot usage-dot-out" aria-hidden="true" />
          {copy.output} <b>{number(channel.output_tokens)}</b>
        </span>
      </p>
      {models.length > 0 && (
        <ul className="usage-channel-models">
          {models.map((item) => (
            <li key={item.model || '_blank'}>
              <span>{item.model || copy.noModelLabel}</span>
              <em>{number(tokens(item))}</em>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}

/** 输入/输出环形占比：一眼看出构成，而不是一条扁进度条 */
function ShareRing({
  inputPct,
  outputPct,
  caption,
  inputLabel,
  ringAria,
  size = 'lg',
}: {
  inputPct: number
  outputPct: number
  caption: string
  inputLabel: string
  ringAria: (caption: string, inputPct: number, outputPct: number) => string
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
      aria-label={ringAria(caption, inputPct, outputPct)}
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
        <span>{inputLabel}</span>
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

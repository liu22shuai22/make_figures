import { FormEvent, useEffect, useId, useRef, useState } from 'react'
import BrandMark from './BrandMark'
import ModelAssistant, { type AssistantDraft } from './ModelAssistant'
import { useLocale } from '../LocaleContext'
import { buildCardinalityProposal } from '../assistantCardinality'
import { ApiError, assistantRecords, assistantTurn, type AssistantBand, type AssistantRecord, type AssistantStep } from '../api'
import { toJsonSpec } from '../spec'

interface AiAssistantProps {
  onUsage: () => void
  onStart: () => void
  onSample: () => void
  onOpen: () => void
  open: boolean
  onOpenChange: (open: boolean) => void
  workbench?: AssistantDraft
  token?: string
  onLocate: (id: string) => void
  /** 欢迎页走「工作台」；工作台页改为「返回首页」 */
  variant?: 'welcome' | 'workbench'
}

type Role = 'bot' | 'user'
type Proposal = NonNullable<ReturnType<typeof buildCardinalityProposal>>

interface Message {
  id: string
  role: Role
  text: string
  band?: AssistantBand
  topic?: string
  trace?: Record<string, unknown>
}

let messageSeq = 0
function nextId() {
  messageSeq += 1
  return `m-${messageSeq}`
}

type RecordTone = 'ok' | 'warn' | 'fail'

function toolSteps(steps: AssistantStep[]) {
  return steps.filter((step) => step.stage === 'tool')
}

function recordTone(steps: AssistantStep[]): RecordTone {
  const statuses = toolSteps(steps).map((step) => step.status)
  if (statuses.some((status) => ['error', 'internal', 'timeout', 'llm', 'config', 'shape'].includes(status))) {
    return 'fail'
  }
  if (statuses.some((status) =>
    ['auth', 'blocked', 'not_workbench', 'diagram_kind', 'no_relation', 'no_binary', 'busy', 'refused', 'no_match'].includes(status))) {
    return 'warn'
  }
  return 'ok'
}

function recordElapsed(steps: AssistantStep[]) {
  if (!steps.length) return 0
  const last = steps[steps.length - 1]
  return last.startMs + last.durationMs
}

function stepTone(status: string): RecordTone {
  if (['error', 'internal', 'timeout', 'llm', 'config', 'shape'].includes(status)) return 'fail'
  if (['auth', 'blocked', 'not_workbench', 'diagram_kind', 'no_relation', 'no_binary', 'busy', 'refused', 'no_match'].includes(status)) {
    return 'warn'
  }
  return 'ok'
}

function formatRecordWhen(
  iso: string,
  locale: string,
  copy: {
    recordJustNow: string
    recordMinutesAgo: (n: number) => string
    recordHoursAgo: (n: number) => string
  },
) {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const delta = Date.now() - date.getTime()
  if (delta >= 0 && delta < 60_000) return copy.recordJustNow
  if (delta >= 0 && delta < 3_600_000) return copy.recordMinutesAgo(Math.floor(delta / 60_000))
  if (delta >= 0 && delta < 86_400_000) return copy.recordHoursAgo(Math.floor(delta / 3_600_000))
  return date.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function AiAssistant({
  onUsage,
  onStart,
  onSample,
  onOpen,
  open,
  onOpenChange,
  workbench,
  token,
  onLocate,
  variant = 'welcome',
}: AiAssistantProps) {
  const { locale, app } = useLocale()
  const a = app.assistant
  const panelId = useId()
  const [view, setView] = useState<'chat' | 'review' | 'records'>('chat')
  const [records, setRecords] = useState<AssistantRecord[]>([])
  const [recordState, setRecordState] = useState<'loading' | 'ready' | 'error'>('ready')
  const [sessionRecords, setSessionRecords] = useState<AssistantRecord[]>([])
  const zh = locale === 'zh'
  const visibleRecords = token ? records : sessionRecords
  useEffect(() => {
    if (!open || view !== 'records' || !token) return
    const controller = new AbortController()
    setRecordState('loading')
    assistantRecords(token, controller.signal).then(items => {
      if (!controller.signal.aborted) { setRecords(items); setRecordState('ready') }
    }).catch(() => { if (!controller.signal.aborted) setRecordState('error') })
    return () => controller.abort()
  }, [open, view, token, sessionRecords])
  const [checkRequest, setCheckRequest] = useState(0)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [proposal, setProposal] = useState<Proposal>()
  const [choices, setChoices] = useState<Proposal[]>([])
  const [messages, setMessages] = useState<Message[]>(() => [
    { id: nextId(), role: 'bot', text: a.greeting },
  ])
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const showQuick = messages.length <= 2

  // 欢迎页切语言时：若还在首句问候，跟着换成对应文案
  useEffect(() => {
    setMessages((prev) => {
      if (prev.length === 1 && prev[0].role === 'bot') {
        return [{ ...prev[0], text: a.greeting }]
      }
      return prev
    })
  }, [locale, a.greeting])

  useEffect(() => {
    if (!open || view !== 'chat') return
    const node = listRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [open, view, messages, busy, proposal, choices])

  useEffect(() => {
    if (open && view === 'chat') inputRef.current?.focus()
  }, [open, view])

  const push = (
    role: Role,
    text: string,
    band?: AssistantBand,
    extra?: { topic?: string; trace?: Record<string, unknown> },
  ) => {
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role, text, band, topic: extra?.topic, trace: extra?.trace },
    ])
  }

  const historyPayload = () =>
    messages
      .filter((item) => item.role === 'user' || item.role === 'bot')
      .slice(-8)
      .map((item) => ({
        role: item.role,
        text: item.text.slice(0, 400),
        band: item.band,
        topic: item.topic,
      }))

  const traceBits = (trace?: Record<string, unknown>) => {
    if (!trace) return []
    const bits: string[] = []
    if (typeof trace.tool === 'string' && trace.tool) bits.push(a.traceTool(trace.tool))
    if (typeof trace.follow_up_of === 'string' && trace.follow_up_of) {
      bits.push(a.traceFollowUp(trace.follow_up_of))
    } else if (typeof trace.topic === 'string' && trace.topic) {
      bits.push(a.traceTopic(trace.topic))
    }
    if (typeof trace.url === 'string' && trace.url) bits.push(a.traceSource('Wikipedia'))
    else if (trace.fallback === 'model_brief') bits.push(a.traceSource('model'))
    return bits
  }

  const selectProposal = (planned: Proposal) => {
    setChoices([])
    if (planned.source !== workbench?.spec || variant !== 'workbench') {
      push('bot', a.cardinalityOutdated)
    } else if (planned.previous === planned.card) {
      push('bot', a.cardinalityAlreadySet(planned.target, planned.card))
    } else {
      setProposal(planned)
    }
  }

  const ask = async (text: string) => {
    const cleaned = text.trim()
    if (!cleaned || busy) return
    push('user', cleaned)
    setDraft('')
    setProposal(undefined)
    setChoices([])
    setBusy(true)
    try {
      const erDraft = variant === 'workbench' && workbench?.applyCardinality ? workbench.spec : undefined
      const turn = await assistantTurn({
        message: cleaned,
        surface: variant,
        locale,
        diagram_kind: variant === 'workbench' ? workbench?.diagramKind ?? 'er' : 'er',
        spec: erDraft ? toJsonSpec(erDraft) : null,
        token,
        history: historyPayload(),
      })

      if (turn.actions.some((item) => item.type === 'open_review')) {
        if (turn.messages.length === 1) setView('review')
        if (workbench?.spec.entities.length) setCheckRequest((previous) => previous + 1)
      }

      const steps = turn.trace?.steps
      if (Array.isArray(steps)) {
        const now = Date.now()
        setSessionRecords(items => [{ id: now, created: new Date(now).toISOString(), steps: steps as AssistantStep[] }, ...items].slice(0, 30))
      }
      for (const item of turn.messages) {
        const trace = item.trace ?? turn.trace
        const topic = typeof trace?.topic === 'string' ? trace.topic : undefined
        push('bot', item.text, item.band ?? turn.band, { topic, trace })
      }

      const erSource = variant === 'workbench' ? workbench?.spec : undefined
      if (turn.cardinality && erSource) {
        const planned = turn.cardinality.choices.flatMap(
          (choice) => buildCardinalityProposal(erSource, choice) ?? [],
        )
        if (planned.length > 1) setChoices(planned)
        else if (planned.length === 1) selectProposal(planned[0])
      }
    } catch (error) {
      push('bot', error instanceof ApiError ? error.message : a.turnFailed, 'refuse')
    } finally {
      setBusy(false)
    }
  }

  const applyProposal = async () => {
    if (!proposal || !workbench?.applyCardinality || busy) return
    if (workbench.spec !== proposal.source || variant !== 'workbench') {
      setProposal(undefined)
      push('bot', a.cardinalityOutdated)
      return
    }
    setBusy(true)
    try {
      const applied = await workbench.applyCardinality(proposal.source, proposal.draft)
      push('bot', applied ? a.cardinalityApplied : a.cardinalityFailed, 'product_tool')
      if (applied) setProposal(undefined)
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void ask(draft)
  }

  const bandLabel = (band?: AssistantBand) => {
    if (!band) return null
    return a.bandLabel[band]
  }

  return (
    <div className={'ai-assist' + (open ? ' is-open' : '')}>
      <div hidden={!open}>
        <section className="ai-assist-panel" id={panelId} aria-label={a.panelAria}>
          <header className="ai-assist-head">
            <div className="ai-assist-title">
              <BrandMark size={30} className="ai-assist-brand" />
              <div>
                <strong>{a.brand}</strong>
                <p>{a.subtitle}</p>
              </div>
            </div>
            <button
              type="button"
              className="ai-assist-close"
              aria-label={a.closeAria}
              onClick={() => onOpenChange(false)}
            >
              ×
            </button>
          </header>

          <div className="ai-assist-tabs" role="tablist" aria-label={a.tabsAria}>
            <button
              type="button"
              role="tab"
              className="ai-assist-tab"
              aria-selected={view === 'chat'}
              onClick={() => setView('chat')}
            >
              {a.tabChat}
            </button>
            <button
              type="button"
              role="tab"
              className="ai-assist-tab"
              aria-selected={view === 'review'}
              onClick={() => setView('review')}
            >
              {a.tabReview}
            </button>
            <button
              type="button"
              role="tab"
              className="ai-assist-tab"
              aria-selected={view === 'records'}
              onClick={() => setView('records')}
            >
              {a.tabRecords}
            </button>
          </div>

          <div className="ai-assist-body" hidden={view !== 'records'}>
            <div className="ai-assist-records">
              <div className="ai-assist-records-head">
                <p className="ai-assist-records-hint">
                  {a.recordsHint}
                  {!token ? ` ${a.recordsGuestHint}` : ''}
                </p>
                {visibleRecords.length > 0 && recordState === 'ready' ? (
                  <span className="ai-assist-records-count">{a.recordsCount(visibleRecords.length)}</span>
                ) : null}
              </div>
              {token && recordState === 'loading' ? (
                <p className="ai-assist-records-empty">{a.recordsLoading}</p>
              ) : token && recordState === 'error' ? (
                <p className="ai-assist-records-empty">{a.recordsError}</p>
              ) : visibleRecords.length === 0 ? (
                <p className="ai-assist-records-empty">{a.recordsEmpty}</p>
              ) : (
                <ul className="ai-assist-record-list">
                  {visibleRecords.map((record) => {
                    const tools = toolSteps(record.steps)
                    const labels = tools.length
                      ? tools.map((step) => a.recordTool[step.name] || step.name)
                      : [a.recordTool.preflight]
                    const tone = recordTone(record.steps)
                    const elapsed = recordElapsed(record.steps)
                    return (
                      <li key={record.id}>
                        <details className={'ai-assist-record is-' + tone} name="ai-assist-records">
                          <summary>
                            <span className="ai-assist-record-tone" aria-hidden="true" />
                            <span className="ai-assist-record-main">
                              <span className="ai-assist-record-tools" aria-label={labels.join(' → ')}>
                                {labels.map((label, index) => (
                                  <span key={`${record.id}-tool-${index}`} className="ai-assist-record-chip">
                                    {index > 0 ? <span className="ai-assist-record-arrow" aria-hidden="true">→</span> : null}
                                    <span>{label}</span>
                                  </span>
                                ))}
                                {tools.length > 1 ? (
                                  <span className="ai-assist-record-tag">
                                    {record.steps.some((step) => step.stage === 'loop')
                                      ? a.recordLoop
                                      : a.recordCombined}
                                  </span>
                                ) : null}
                              </span>
                              <span className="ai-assist-record-meta">
                                <span className={'ai-assist-record-outcome is-' + tone}>
                                  {a.recordOutcome[tone]}
                                </span>
                                <span>{formatRecordWhen(record.created, locale, a)}</span>
                                {elapsed > 0 ? <span>{a.recordDuration(elapsed)}</span> : null}
                              </span>
                            </span>
                            <span className="ai-assist-record-chevron" aria-hidden="true" />
                          </summary>
                          <ol className="ai-assist-record-steps">
                            {record.steps.map((step, index) => {
                              const rowTone = step.stage === 'tool' ? stepTone(step.status) : 'ok'
                              return (
                                <li
                                  key={`${record.id}-${index}`}
                                  className={
                                    'ai-assist-record-step is-' + rowTone
                                    + (step.stage === 'tool' ? ' is-tool' : ' is-quiet')
                                  }
                                >
                                  <span className="ai-assist-record-step-rail" aria-hidden="true" />
                                  <span className="ai-assist-record-step-body">
                                    <span className="ai-assist-record-step-top">
                                      <span className="ai-assist-record-step-stage">
                                        {a.recordStage[step.stage] || step.stage}
                                      </span>
                                      <span className="ai-assist-record-step-name">
                                        {a.recordTool[step.name] || step.name}
                                      </span>
                                    </span>
                                    <span className="ai-assist-record-step-bottom">
                                      <span className="ai-assist-record-step-status">
                                        {a.recordStatus[step.status] || step.status}
                                      </span>
                                      <span className="ai-assist-record-step-time">
                                        {a.recordDuration(step.durationMs)}
                                      </span>
                                    </span>
                                  </span>
                                </li>
                              )
                            })}
                          </ol>
                        </details>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </div>

          <div className="ai-assist-body" hidden={view !== 'review'}>
            <div className="ai-assist-review">
              {variant === 'workbench' && workbench?.diagramKind === 'usecase' && (
                <section aria-label={a.reviewAria}>
                  <strong>{zh ? '用例图结构检查' : 'Use-case structure check'}</strong>
                  {workbench.issues.length ? <ul>{workbench.issues.map((issue, index) =>
                    <li key={index}>{issue.message}</li>)}</ul> : <p>{workbench.useCaseCount
                      ? (zh ? '当前草稿通过结构检查。' : 'The draft passed structural checks.')
                      : (zh ? '请先载入用例草稿。' : 'Open a use-case draft first.')}</p>}
                </section>)}
              {variant === 'workbench' && workbench && workbench.diagramKind !== 'usecase' && (
                <ModelAssistant
                  key={token ?? ''}
                  {...workbench}
                  token={token}
                  checkRequest={checkRequest}
                  onLocate={onLocate}
                />
              )}
            </div>
            {variant === 'welcome' && (
              <div className="ai-assist-links">
                <button type="button" className="ai-assist-link is-accent" onClick={onStart}>
                  {a.enterWorkbench}
                </button>
              </div>
            )}
          </div>

          <div className="ai-assist-body" hidden={view !== 'chat'}>
            <div className="ai-assist-messages" ref={listRef}>
              {messages.map((message) => (
                <div key={message.id} className={'ai-assist-bubble is-' + message.role}>
                  {message.role === 'bot' && message.band && (
                    <span className={'ai-assist-band is-' + message.band}>{bandLabel(message.band)}</span>
                  )}
                  <div className="ai-assist-text">{message.text}</div>
                  {message.trace?.tool === 'usage.explain' && <button type="button" className="btn btn-sm"
                    onClick={onUsage}>{zh ? '查看 Token 用量' : 'View token usage'}</button>}
                  {message.trace?.tool === 'draft.open_review' && !message.trace.blocked && <button type="button"
                    className="btn btn-sm" onClick={() => setView('review')}>{a.tabReview}</button>}
                  {message.role === 'bot' && traceBits(message.trace).length > 0 && (
                    <div className="ai-assist-trace">
                      {traceBits(message.trace).map((bit) => (
                        <span key={bit}>{bit}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {choices.length > 0 && (
                <div className="ai-assist-bubble is-bot">
                  <p>{a.cardinalityChooseRelation}</p>
                  {choices.map((choice) => (
                    <button type="button" className="btn btn-sm" key={choice.relationIndex}
                      onClick={() => selectProposal(choice)} disabled={busy}>
                      {a.cardinalityChoice(choice.relationIndex + 1, choice.relation, choice.target, choice.previous)}
                    </button>
                  ))}
                </div>
              )}
              {proposal && (
                <div className="ai-assist-bubble is-bot">
                  <p>{a.cardinalityProposal(proposal.relation, proposal.target, proposal.previous, proposal.card)}</p>
                  {!token && <p>{a.cardinalityLogin}</p>}
                  <button type="button" className="btn btn-sm btn-primary" disabled={busy || !token}
                    onClick={() => void applyProposal()}>{a.cardinalityApply}</button>
                  <button type="button" className="btn btn-sm" disabled={busy}
                    onClick={() => setProposal(undefined)}>{a.cardinalityCancel}</button>
                </div>
              )}
              {busy && <div className="ai-assist-bubble is-bot is-typing">{a.typing}</div>}
            </div>

            {showQuick && (
              <div className="ai-assist-quick" aria-label={a.quickAria}>
                {a.quick.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className="ai-assist-chip"
                    onClick={() => void ask(item)}
                    disabled={busy}
                  >
                    {item}
                  </button>
                ))}
              </div>
            )}

            <div className="ai-assist-composer">
              <form className="ai-assist-form" onSubmit={onSubmit}>
                <input
                  ref={inputRef}
                  className="input"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder={a.placeholder}
                  aria-label={a.askAria}
                  maxLength={200}
                  disabled={busy}
                />
                <button type="submit" className="btn btn-primary" disabled={busy || !draft.trim()}>
                  {a.send}
                </button>
              </form>
              <div className="ai-assist-links">
                <button type="button" className="ai-assist-link is-accent" onClick={onStart}>
                  {variant === 'workbench' ? a.goDescribe : a.startDrawing}
                </button>
                <span className="ai-assist-dot" aria-hidden="true" />
                <button type="button" className="ai-assist-link" onClick={onSample}>
                  {variant === 'workbench' ? a.loadSample : a.trySample}
                </button>
                <span className="ai-assist-dot" aria-hidden="true" />
                <button type="button" className="ai-assist-link" onClick={onOpen}>
                  {variant === 'workbench' ? a.backHome : a.workbench}
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>

      <button
        type="button"
        className="ai-assist-fab"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? a.closeAria : a.openAria}
        onClick={() => onOpenChange(!open)}
        data-testid="ai-assistant"
      >
        <span className="ai-assist-fab-glow" aria-hidden="true" />
        {open ? (
          <span className="ai-assist-fab-icon is-close" aria-hidden="true">
            ×
          </span>
        ) : (
          <BrandMark size={28} className="ai-assist-fab-brand" />
        )}
        <span className="ai-assist-fab-label">{open ? a.close : a.brand}</span>
      </button>
    </div>
  )
}

import { FormEvent, useEffect, useId, useRef, useState } from 'react'
import BrandMark from './BrandMark'
import ModelAssistant, { type AssistantDraft } from './ModelAssistant'
import { useLocale } from '../LocaleContext'
import { buildCardinalityProposal } from '../assistantCardinality'
import { ApiError, suggestCardinality } from '../api'
import { toJsonSpec } from '../spec'

interface AiAssistantProps {
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
}

let messageSeq = 0
function nextId() {
  messageSeq += 1
  return `m-${messageSeq}`
}

export default function AiAssistant({
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
  const [view, setView] = useState<'chat' | 'review'>('chat')
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

  const push = (role: Role, text: string) => {
    setMessages((prev) => [...prev, { id: nextId(), role, text }])
  }

  const replyTo = (input: string): string => {
    const text = input.trim().toLowerCase()
    if (!text) return a.emptyPrompt
    const hit = a.knowledge.find((item) => item.keys.some((key) => text.includes(key.toLowerCase())))
    if (hit) return hit.answer
    return a.fallback
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
    if (a.checkIntent.test(cleaned)) {
      setView('review')
      if (workbench?.spec.entities.length) setCheckRequest((previous) => previous + 1)
      return
    }
    const reply = replyTo(cleaned)
    const erDraft = variant === 'workbench' && workbench?.applyCardinality ? workbench.spec : undefined
    if (a.editIntent.test(cleaned) || /限制|只能|仅能|最多|至多|不超过|基数/.test(cleaned)
        || (erDraft?.relations.length && reply === a.fallback)) {
      if (!erDraft?.relations.length) {
        push('bot', a.cardinalityNeedDraft)
        return
      }
      if (!token) {
        push('bot', a.cardinalityLogin)
        return
      }
      setBusy(true)
      try {
        const suggested = await suggestCardinality(cleaned, toJsonSpec(erDraft), token)
        const planned = suggested.choices.flatMap((choice) => buildCardinalityProposal(erDraft, choice) ?? [])
        push('bot', a.cardinalityModelUsed(suggested.model))
        if (planned.length > 1) setChoices(planned)
        else if (planned.length === 1) selectProposal(planned[0])
        else push('bot', a.editNotReady)
      } catch (error) {
        push('bot', error instanceof ApiError ? error.message : a.cardinalityFailed)
      } finally {
        setBusy(false)
      }
      return
    }
    setBusy(true)
    window.setTimeout(() => {
      push('bot', reply)
      setBusy(false)
    }, 380)
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
      push('bot', applied ? a.cardinalityApplied : a.cardinalityFailed)
      if (applied) setProposal(undefined)
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    void ask(draft)
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
          </div>

          <div className="ai-assist-body" hidden={view !== 'review'}>
            <div className="ai-assist-review">
              {workbench && (
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
                  {message.text}
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

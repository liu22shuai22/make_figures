import { FormEvent, useEffect, useId, useRef, useState } from 'react'
import BrandMark from './BrandMark'
import ModelAssistant, { type AssistantDraft } from './ModelAssistant'
import { useLocale } from '../LocaleContext'

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
  }, [open, view, messages, busy])

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

  const ask = (text: string) => {
    const cleaned = text.trim()
    if (!cleaned || busy) return
    push('user', cleaned)
    setDraft('')
    if (a.checkIntent.test(cleaned)) {
      setView('review')
      if (workbench?.spec.entities.length) setCheckRequest((previous) => previous + 1)
      return
    }
    if (a.editIntent.test(cleaned)) {
      push('bot', a.editNotReady)
      return
    }
    setBusy(true)
    window.setTimeout(() => {
      push('bot', replyTo(cleaned))
      setBusy(false)
    }, 380)
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    ask(draft)
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
              {busy && <div className="ai-assist-bubble is-bot is-typing">{a.typing}</div>}
            </div>

            {showQuick && (
              <div className="ai-assist-quick" aria-label={a.quickAria}>
                {a.quick.map((item) => (
                  <button
                    key={item}
                    type="button"
                    className="ai-assist-chip"
                    onClick={() => ask(item)}
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

import { FormEvent, useEffect, useId, useRef, useState } from 'react'
import BrandMark from './BrandMark'
import ModelAssistant, { type AssistantDraft } from './ModelAssistant'

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

const QUICK = [
  '怎么开始？',
  '图还能改吗？',
  '导出会糊吗？',
  '什么是语义沙？',
]

const KNOWLEDGE: { keys: string[]; answer: string }[] = [
  {
    keys: ['开始', '怎么用', '入门', '如何', '流程'],
    answer:
      '三步就够：① 点「开始绘图」用自然语言描述系统；② 在工作台核对实体、联系和基数；③ 排版后下载 PNG 或 SVG。也可以先点「体验示例」看选课系统怎么出图。',
  },
  {
    keys: ['还能改', '能改吗', '怎么改', '如何编辑', '怎么编辑', '怎么微调', '怎么拖'],
    answer:
      '能改。生成结果是表单不是死图：加字段、改主键、调基数、拖动布局都可以，改完重新排版即可，不用重写描述。',
  },
  {
    keys: ['导出', '下载', '糊', 'png', 'svg', 'word'],
    answer:
      '贴进 Word 用 PNG，按当前画布出图；要打印或继续放大用 SVG，矢量放大不失真。两种格式都在预览区一键下载。',
  },
  {
    keys: ['语义沙', '物质', '未来', '人工智能', 'ai'],
    answer:
      '「语义沙」是 ERFlow 对 AI × E-R 的想象：描述像沙粒一样被聚成可编辑的结构——节点是实体，细丝是联系，还能继续生长和改写。你现在用的工作台，就是把这句话落成可用的工具。',
  },
  {
    keys: ['多大', '上限', '多少', '实体', '联系'],
    answer: '单个系统最多 24 个实体、40 条联系，每个实体或联系最多 12 个属性。超出时工作台会说明原因。',
  },
  {
    keys: ['保存', '上传', '隐私', '本地'],
    answer:
      '描述只用于当次生成，不写入数据库；规格与图默认只在你浏览器里。用量页只统计请求数和 token，不保留原文。',
  },
  {
    keys: ['sgi', '通向'],
    answer: '「通向SGI」是 ERFlow 的品牌去向。需要外链时，把目标网址配进站点配置即可。',
  },
  {
    keys: ['登录', '注册', '账号'],
    answer: '生成与排版需要登录。欢迎页右上角可进入登录；未登录时仍可浏览介绍，并先体验页面说明。',
  },
]

function replyTo(input: string): string {
  const text = input.trim().toLowerCase()
  if (!text) return '可以说说你想了解的：怎么开始、能不能改图、怎么导出，或「语义沙」是什么。'
  const hit = KNOWLEDGE.find((item) => item.keys.some((key) => text.includes(key.toLowerCase())))
  if (hit) return hit.answer
  return '我是 ERFlow 的语义沙向导，可以介绍怎么开始、图能否编辑、导出格式、系统上限，以及语义沙本身。也可以直接点下方入口进入工作台。'
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
  const panelId = useId()
  const [view, setView] = useState<'chat' | 'review'>('chat')
  const [checkRequest, setCheckRequest] = useState(0)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [messages, setMessages] = useState<Message[]>(() => [
    {
      id: nextId(),
      role: 'bot',
      text: '你好，我是语义沙。可以问怎么用 ERFlow，或让我检查当前草稿。',
    },
  ])
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const showQuick = messages.length <= 2

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

  const ask = (text: string) => {
    const cleaned = text.trim()
    if (!cleaned || busy) return
    push('user', cleaned)
    setDraft('')
    if (/^(?:请\s*)?(?:帮我\s*)?(?:检查|审查|核对)(?:一下)?/.test(cleaned)) {
      setView('review')
      if (workbench?.spec.entities.length) setCheckRequest((previous) => previous + 1)
      return
    }
    if (/改成|改为|替换|帮我改|^(?:请\s*)?(?:帮我\s*)?(?:修改|添加|删除)/.test(cleaned)) {
      push(
        'bot',
        '一句话改图还未接入。你可以在工作台编辑实体、联系和基数，也可以切到「检查模型」让我核对当前草稿。',
      )
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
        <section className="ai-assist-panel" id={panelId} aria-label="语义沙 · ERFlow 助手">
          <header className="ai-assist-head">
            <div className="ai-assist-title">
              <BrandMark size={30} className="ai-assist-brand" />
              <div>
                <strong>语义沙</strong>
                <p>ERFlow 助手</p>
              </div>
            </div>
            <button
              type="button"
              className="ai-assist-close"
              aria-label="关闭语义沙"
              onClick={() => onOpenChange(false)}
            >
              ×
            </button>
          </header>

          <div className="ai-assist-tabs" role="tablist" aria-label="助手功能">
            <button
              type="button"
              role="tab"
              className="ai-assist-tab"
              aria-selected={view === 'chat'}
              onClick={() => setView('chat')}
            >
              使用问答
            </button>
            <button
              type="button"
              role="tab"
              className="ai-assist-tab"
              aria-selected={view === 'review'}
              onClick={() => setView('review')}
            >
              检查模型
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
                  进入工作台
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
              {busy && <div className="ai-assist-bubble is-bot is-typing">沙粒聚拢中…</div>}
            </div>

            {showQuick && (
              <div className="ai-assist-quick" aria-label="快捷问题">
                {QUICK.map((item) => (
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
                  placeholder="问问语义沙…"
                  aria-label="向语义沙提问"
                  maxLength={200}
                  disabled={busy}
                />
                <button type="submit" className="btn btn-primary" disabled={busy || !draft.trim()}>
                  发送
                </button>
              </form>
              <div className="ai-assist-links">
                <button type="button" className="ai-assist-link is-accent" onClick={onStart}>
                  {variant === 'workbench' ? '去描述' : '开始绘图'}
                </button>
                <span className="ai-assist-dot" aria-hidden="true" />
                <button type="button" className="ai-assist-link" onClick={onSample}>
                  {variant === 'workbench' ? '载入样例' : '体验示例'}
                </button>
                <span className="ai-assist-dot" aria-hidden="true" />
                <button type="button" className="ai-assist-link" onClick={onOpen}>
                  {variant === 'workbench' ? '返回首页' : '工作台'}
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
        aria-label={open ? '关闭语义沙' : '打开语义沙'}
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
        <span className="ai-assist-fab-label">{open ? '关闭' : '语义沙'}</span>
      </button>
    </div>
  )
}

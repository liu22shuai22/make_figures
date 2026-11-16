import type { ChangeEvent } from 'react'
import type { CanvasRatio } from '../types'
import CanvasRatioSelect from './CanvasRatioSelect'

export const DESCRIBE_LIMIT = 4000

const STARTERS: { id: string; label: string; text: string }[] = [
  {
    id: 'library',
    label: '图书借阅',
    text: '读者可以借阅多本图书，同一本图书也可以被不同读者先后借阅，每次借阅要记录借出日期和归还日期；每本图书属于一个馆藏分类。',
  },
  {
    id: 'shop',
    label: '电商订单',
    text: '用户可以下多个订单，一个订单可以包含多种商品，每件商品要记录购买数量和成交单价；每个订单通过一次支付结清，支付记录支付方式与支付时间。',
  },
  {
    id: 'hr',
    label: '人事考勤',
    text: '员工隶属于一个部门，每个部门可以有多名员工；员工每天打卡产生考勤记录，记录打卡时间和状态；员工可以提交请假单，请假单记录开始日期、结束日期和审批结果。',
  },
]

interface DescribeBoxProps {
  text: string
  onTextChange: (value: string) => void
  onGenerate: () => void
  generating: boolean
  rendering: boolean
  replacing: boolean
  ratio: CanvasRatio
  onRatioChange: (ratio: CanvasRatio) => void
  /** 本地校验错误（为空、超过字数等） */
  error: string | null
  /** 当前接通渠道短提示；点开 API 平台 */
  channelLabel?: string | null
  onOpenChannel?: () => void
  /** 空态快捷载入选课样例 */
  onLoadSample?: () => void
  /** 是否已登录；未登录时露出登录引导 */
  loggedIn?: boolean
  onLogin?: () => void
}

export default function DescribeBox({
  text,
  onTextChange,
  onGenerate,
  generating,
  rendering,
  replacing,
  ratio,
  onRatioChange,
  error,
  channelLabel,
  onOpenChannel,
  onLoadSample,
  loggedIn = true,
  onLogin,
}: DescribeBoxProps) {
  const length = Array.from(text.trim()).length
  const empty = length === 0
  const overLimit = length > DESCRIBE_LIMIT

  const busy = generating || rendering
  const phaseLabel = rendering ? '正在排版出图' : generating ? '正在生成规格' : null

  return (
    <section className={`describe${busy ? ' is-busy' : ''}`} aria-labelledby="describe-title" aria-busy={busy}>
      <div className="describe-head">
        <h3 id="describe-title">描述你的系统</h3>
        {phaseLabel ? (
          <span className="describe-status" data-testid="describe-status">
            <span className="spinner spinner-sm spinner-accent" aria-hidden="true" />
            <span>
              <strong>{phaseLabel}</strong>
              {generating && !rendering ? ' · 复杂需求可能需要一分钟' : ''}
            </span>
          </span>
        ) : !loggedIn && onLogin ? (
          <button type="button" className="describe-login" onClick={onLogin} data-testid="describe-login">
            未登录 · 去登录
          </button>
        ) : (
          channelLabel && onOpenChannel && (
            <button type="button" className="describe-channel" onClick={onOpenChannel}>
              {channelLabel}
            </button>
          )
        )}
      </div>

      <textarea
        className="textarea"
        rows={5}
        value={text}
        placeholder={replacing ? '输入下一份系统描述' : '例如：图书馆管理系统，读者借阅图书，图书属于分类'}
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onTextChange(event.target.value)}
        aria-describedby="describe-counter"
        data-testid="describe-input"
        disabled={busy}
      />

      {!replacing && empty && (
        <div className="describe-starters">
          <span>试一个例子</span>
          {STARTERS.map((starter) => (
            <button
              key={starter.id}
              type="button"
              className="starter"
              onClick={() => onTextChange(starter.text)}
              data-testid={`starter-${starter.id}`}
            >
              {starter.label}
            </button>
          ))}
          {onLoadSample && (
            <button
              type="button"
              className="starter starter-sample"
              onClick={onLoadSample}
              disabled={generating || rendering}
              data-testid="load-sample"
            >
              选课样例出图
            </button>
          )}
        </div>
      )}

      <div className="describe-foot">
        <span
          id="describe-counter"
          className={`counter${overLimit ? ' is-over' : ''}`}
          data-testid="describe-counter"
        >
          {length} / {DESCRIBE_LIMIT} 字
        </span>
        <CanvasRatioSelect ratio={ratio} onChange={onRatioChange} disabled={busy} />
        <button
          type="button"
          className={busy ? 'btn btn-primary is-busy' : replacing ? 'btn btn-generate' : 'btn btn-primary'}
          onClick={onGenerate}
          disabled={busy || empty || overLimit}
          title={
            empty
              ? '先写一段系统描述'
              : overLimit
                ? '描述超过 4000 字，需要精简'
                : !loggedIn
                  ? '登录后才能生成'
                  : replacing
                    ? '新图生成后替换当前草稿'
                    : '生成模型并自动排版'
          }
          data-testid="generate"
          aria-busy={busy}
        >
          {busy ? (
            <>
              <span className="spinner spinner-sm" aria-hidden="true" />
              {rendering ? '排版中…' : '生成中…'}
            </>
          ) : !loggedIn ? (
            '登录后生成'
          ) : replacing ? (
            '生成新图并替换'
          ) : (
            '生成 E-R 图'
          )}
        </button>
      </div>

      {error && (
        <p className="field-error" role="alert" data-testid="describe-error">
          {error}
          {onLogin && /登录/.test(error) && (
            <>
              {' '}
              <button type="button" className="link-btn" onClick={onLogin}>
                去登录
              </button>
            </>
          )}
        </p>
      )}
    </section>
  )
}

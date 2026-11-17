import type { ChangeEvent } from 'react'
import type { CanvasRatio, DiagramKind } from '../types'
import CanvasRatioSelect from './CanvasRatioSelect'
import { useLocale } from '../LocaleContext'

export const DESCRIBE_LIMIT = 4000

const ER_STARTER_TEXTS: Record<string, string> = {
  library:
    '读者可以借阅多本图书，同一本图书也可以被不同读者先后借阅，每次借阅要记录借出日期和归还日期；每本图书属于一个馆藏分类。',
  shop:
    '用户可以下多个订单，一个订单可以包含多种商品，每件商品要记录购买数量和成交单价；每个订单通过一次支付结清，支付记录支付方式与支付时间。',
  hr: '员工隶属于一个部门，每个部门可以有多名员工；员工每天打卡产生考勤记录，记录打卡时间和状态；员工可以提交请假单，请假单记录开始日期、结束日期和审批结果。',
}

const USECASE_STARTER_TEXTS: Record<string, string> = {
  library: '图书借阅系统里，读者可以借书、还书和查询馆藏；管理员也可以办理借书、还书，并协助查询馆藏。',
  ticket: '在线订票系统中，旅客可以查询车次、下单购票和退票；客服可以协助退票与改签咨询。',
  campus: '选课系统里，学生可以查询课程、选课和退课；教务员可以发布课程并审核容量调整。',
}

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
  /** 空态快捷载入样例 */
  onLoadSample?: () => void
  sampleLabel?: string
  /** 是否已登录；未登录时露出登录引导 */
  loggedIn?: boolean
  onLogin?: () => void
  diagramKind?: DiagramKind
  /** 用例图等后端未通时：生成按钮可点，由上层给出提示 */
  generateDisabledReason?: string | null
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
  sampleLabel,
  loggedIn = true,
  onLogin,
  diagramKind = 'er',
  generateDisabledReason = null,
}: DescribeBoxProps) {
  const { app } = useLocale()
  const d = app.describe
  const length = Array.from(text.trim()).length
  const empty = length === 0
  const overLimit = length > DESCRIBE_LIMIT
  const isUseCase = diagramKind === 'usecase'
  const starters = isUseCase
    ? [
        { id: 'library', label: d.starterLib, text: USECASE_STARTER_TEXTS.library },
        { id: 'ticket', label: d.starterTicket, text: USECASE_STARTER_TEXTS.ticket },
        { id: 'campus', label: d.starterCampus, text: USECASE_STARTER_TEXTS.campus },
      ]
    : [
        { id: 'library', label: d.starterLib, text: ER_STARTER_TEXTS.library },
        { id: 'shop', label: d.starterShop, text: ER_STARTER_TEXTS.shop },
        { id: 'hr', label: d.starterHr, text: ER_STARTER_TEXTS.hr },
      ]

  const busy = generating || rendering
  const phaseLabel = rendering ? d.phaseLayout : generating ? d.phaseGen : null
  const generateBlocked = Boolean(generateDisabledReason)

  return (
    <section className={`describe${busy ? ' is-busy' : ''}`} aria-labelledby="describe-title" aria-busy={busy}>
      <div className="describe-head">
        <h3 id="describe-title">{isUseCase ? d.titleUc : d.titleEr}</h3>
        {phaseLabel ? (
          <span className="describe-status" data-testid="describe-status">
            <span className="spinner spinner-sm spinner-accent" aria-hidden="true" />
            <span>
              <strong>{phaseLabel}</strong>
              {generating && !rendering ? d.complexWait : ''}
            </span>
          </span>
        ) : !loggedIn && onLogin ? (
          <button type="button" className="describe-login" onClick={onLogin} data-testid="describe-login">
            {d.notLogged}
          </button>
        ) : (
          channelLabel &&
          onOpenChannel && (
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
        placeholder={
          replacing ? (isUseCase ? d.phNextUc : d.phNextEr) : isUseCase ? d.phUc : d.phEr
        }
        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onTextChange(event.target.value)}
        aria-describedby="describe-counter"
        data-testid="describe-input"
        disabled={busy}
      />

      {!replacing && empty && (
        <div className="describe-starters">
          <span>{d.tryExample}</span>
          {starters.map((starter) => (
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
              {sampleLabel || (isUseCase ? app.sampleUc : app.sampleEr)}
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
          {length} / {DESCRIBE_LIMIT} {d.chars}
        </span>
        <CanvasRatioSelect ratio={ratio} onChange={onRatioChange} disabled={busy || generateBlocked} />
        <button
          type="button"
          className={busy ? 'btn btn-primary is-busy' : replacing ? 'btn btn-generate' : 'btn btn-primary'}
          onClick={onGenerate}
          disabled={busy || empty || overLimit}
          title={
            empty
              ? d.writeFirst
              : overLimit
                ? d.overLimit
                : generateDisabledReason
                  ? generateDisabledReason
                  : !loggedIn
                    ? d.loginToGen
                    : replacing
                      ? d.replaceDraft
                      : isUseCase
                        ? d.genUcSpec
                        : d.genErAuto
          }
          data-testid="generate"
          aria-busy={busy}
        >
          {busy ? (
            <>
              <span className="spinner spinner-sm" aria-hidden="true" />
              {rendering ? app.busyLayoutEllipsis : app.busyGenerateEllipsis}
            </>
          ) : !loggedIn && !generateBlocked ? (
            d.loginThenGen
          ) : replacing ? (
            isUseCase ? d.genReplaceUc : d.genReplaceEr
          ) : isUseCase ? (
            d.genUc
          ) : (
            d.genEr
          )}
        </button>
      </div>

      {error && (
        <p className="field-error" role="alert" data-testid="describe-error">
          {error}
          {onLogin && (error.includes('登录') || /sign in/i.test(error)) && (
            <>
              {' '}
              <button type="button" className="link-btn" onClick={onLogin}>
                {app.goLogin}
              </button>
            </>
          )}
        </p>
      )}
    </section>
  )
}

import { useEffect, useRef, useState } from 'react'
import { reviewSpec, type ModelReview } from '../api'
import { toJsonSpec, type Issue } from '../spec'
import type { SpecDraft } from '../types'

export interface AssistantDraft {
  spec: SpecDraft
  issues: Issue[]
  onLocate: (id: string) => void
}

interface Props extends AssistantDraft {
  token?: string
  checkRequest: number
}

export default function ModelAssistant({ spec, issues, token, onLocate, checkRequest }: Props) {
  const inFlight = useRef(false)
  const lastRequest = useRef(checkRequest)
  const [busy, setBusy] = useState(false)
  const [report, setReport] = useState<{ spec: SpecDraft; review?: ModelReview; error?: string }>()
  const current = report?.spec === spec ? report : undefined
  const review = current?.review
  const hasErrors = issues.some((issue) => issue.level === 'error')

  const check = async () => {
    if (inFlight.current || spec.entities.length === 0) return
    const snapshot = { spec }
    setReport(snapshot)
    if (hasErrors || !token) return
    inFlight.current = true
    setBusy(true)
    try {
      setReport({ ...snapshot, review: await reviewSpec(toJsonSpec(spec), token) })
    } catch (caught) {
      setReport({ ...snapshot, error: (caught as Error).message })
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }

  useEffect(() => {
    if (checkRequest <= lastRequest.current) return
    lastRequest.current = checkRequest
    void check()
  }, [checkRequest])

  const findings = [
    ...issues.map((issue) => ({ message: issue.message, targetId: issue.targetId, label: issue.level === 'error' ? '结构错误' : '结构提醒' })),
    ...(review?.structural ?? []).map((item) => ({
      message: item.message,
      targetId: item.index == null ? undefined : item.kind === 'entity' ? spec.entities[item.index]?.id :
        item.kind === 'relation' ? spec.relations[item.index]?.id : undefined,
      label: '结构提醒',
    })),
  ]

  return (
    <section className="model-assistant" aria-label="模型检查">
      <div className="model-assistant-head">
        <span className="hint">本地规则检查</span>
        <button type="button" className="btn btn-sm" disabled={busy || spec.entities.length === 0} onClick={() => void check()}>
          {busy ? '正在检查…' : '检查模型'}
        </button>
      </div>
      {spec.entities.length === 0 && <p className="hint">先生成、导入或添加实体，再检查模型。</p>}
      {report && !current && <p className="hint" role="status">草稿已变化，请重新检查。</p>}
      {current && (
        <div aria-live="polite">
          {findings.length > 0 && <ul className="model-findings">
            {findings.map(({ message, targetId, label }, index) => (
              <li key={index}>
                <span className="badge badge-quiet">{label}</span>
                <span>{message}</span>
                {targetId && <button type="button" className="link-btn" onClick={() => onLocate(targetId)}>定位</button>}
              </li>
            ))}
          </ul>}
          {!hasErrors && !token && <p className="hint">已检查本地规则。登录后可检查重复联系。</p>}
          {current.error && <p className="field-error">{current.error}</p>}
          {review && findings.length === 0 && <p className="hint">本次结构检查未发现问题。</p>}
        </div>
      )}
    </section>
  )
}

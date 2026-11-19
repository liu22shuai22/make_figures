import { useEffect, useRef, useState } from 'react'
import { reviewSpec, type ModelReview } from '../api'
import { toJsonSpec, type Issue } from '../spec'
import type { SpecDraft } from '../types'
import { useLocale } from '../LocaleContext'

export interface AssistantDraft {
  diagramKind?: 'er' | 'usecase'
  useCaseCount?: number
  spec: SpecDraft
  issues: Issue[]
  onLocate: (id: string) => void
  applyCardinality?: (source: SpecDraft, draft: SpecDraft) => Promise<boolean>
}

interface Props extends AssistantDraft {
  token?: string
  checkRequest: number
}

export default function ModelAssistant({ spec, issues, token, onLocate, checkRequest }: Props) {
  const { app } = useLocale()
  const a = app.assistant
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
    ...issues.map((issue) => ({
      message: issue.message,
      targetId: issue.targetId,
      label: issue.level === 'error' ? a.structError : a.structHint,
    })),
    ...(review?.structural ?? []).map((item) => ({
      message: item.message,
      targetId:
        item.index == null
          ? undefined
          : item.kind === 'entity'
            ? spec.entities[item.index]?.id
            : item.kind === 'relation'
              ? spec.relations[item.index]?.id
              : undefined,
      label: a.structHint,
    })),
  ]

  return (
    <section className="model-assistant" aria-label={a.reviewAria}>
      <div className="model-assistant-head">
        <span className="hint">{a.localRules}</span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={busy || spec.entities.length === 0}
          onClick={() => void check()}
        >
          {busy ? a.checking : a.checkModel}
        </button>
      </div>
      {spec.entities.length === 0 && <p className="hint">{a.needEntities}</p>}
      {report && !current && (
        <p className="hint" role="status">
          {a.draftChanged}
        </p>
      )}
      {current && (
        <div aria-live="polite">
          {findings.length > 0 && (
            <ul className="model-findings">
              {findings.map(({ message, targetId, label }, index) => (
                <li key={index}>
                  <span className="badge badge-quiet">{label}</span>
                  <span>{message}</span>
                  {targetId && (
                    <button type="button" className="link-btn" onClick={() => onLocate(targetId)}>
                      {a.locate}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {!hasErrors && !token && <p className="hint">{a.localOkLogin}</p>}
          {current.error && <p className="field-error">{current.error}</p>}
          {review && findings.length === 0 && <p className="hint">{a.noFindings}</p>}
        </div>
      )}
    </section>
  )
}

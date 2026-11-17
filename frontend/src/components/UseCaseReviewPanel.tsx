import type { UseCaseReview, UseCaseReviewFinding } from '../api'

export type UseCaseReviewOutcome = UseCaseReview | { status: 'error'; detail: string }

const findingLabels: Record<UseCaseReviewFinding['kind'], string> = {
  responsibility: '角色职责',
  omission: '用例遗漏',
  dependency: '依赖用法',
}

interface Props {
  outcome: UseCaseReviewOutcome | null
  outdated: boolean
  canReview: boolean
  onReview: () => void
}

export default function UseCaseReviewPanel({ outcome, outdated, canReview, onReview }: Props) {
  const retry = outcome?.status === 'error' || outcome?.status === 'unavailable'
  const findings = !outdated && outcome?.status === 'complete' ? outcome.findings : []
  const status = outdated ? '草稿已编辑，可按原描述检查当前版本。' :
    !outcome ? '正在对照原描述检查角色、用例和依赖。' :
    outcome.status === 'error' ? outcome.detail :
    outcome.status === 'unavailable' ? '业务审查暂时不可用，草稿可继续编辑和排版。' :
    findings.length > 0 ? '可参考以下意见，直接在表单里修改。' : '本次未发现有原文依据的业务问题。'

  return (
    <section className="usecase-review" aria-labelledby="usecase-review-title" data-testid="usecase-review">
      <div className="describe-head">
        <h3 id="usecase-review-title">业务审查</h3>
        {(outdated || retry) && (
          <button type="button" className="btn btn-sm" onClick={onReview} disabled={!canReview || !outcome}>
            {outdated ? '审查当前草稿' : '重试审查'}
          </button>
        )}
      </div>
      <p className="hint" role="status">{status}</p>
      {findings.length > 0 && (
        <ul className="usecase-review-findings">
          {findings.map((finding, index) => (
            <li key={index}>
              <strong>{finding.disposition === 'confirm' ? '待确认' : findingLabels[finding.kind]} · {finding.message}</strong>
              <p>原文「{finding.evidence}」</p>
              <p>{finding.suggestion}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

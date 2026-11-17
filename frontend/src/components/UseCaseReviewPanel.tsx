import type { UseCaseReview, UseCaseReviewFinding } from '../api'
import { useLocale } from '../LocaleContext'

export type UseCaseReviewOutcome = UseCaseReview | { status: 'error'; detail: string }

interface Props {
  outcome: UseCaseReviewOutcome | null
  outdated: boolean
  canReview: boolean
  onReview: () => void
}

export default function UseCaseReviewPanel({ outcome, outdated, canReview, onReview }: Props) {
  const { app } = useLocale()
  const f = app.form
  const findingLabels: Record<UseCaseReviewFinding['kind'], string> = {
    responsibility: f.kindResponsibility,
    omission: f.kindOmission,
    dependency: f.kindDependency,
  }
  const retry = outcome?.status === 'error' || outcome?.status === 'unavailable'
  const findings = !outdated && outcome?.status === 'complete' ? outcome.findings : []
  const status = outdated
    ? f.reviewOutdated
    : !outcome
      ? f.reviewBusy
      : outcome.status === 'error'
        ? outcome.detail
        : outcome.status === 'unavailable'
          ? f.reviewUnavailable
          : findings.length > 0
            ? f.reviewHints
            : f.reviewClean

  return (
    <section className="usecase-review" aria-labelledby="usecase-review-title" data-testid="usecase-review">
      <div className="describe-head">
        <h3 id="usecase-review-title">{f.reviewTitle}</h3>
        {(outdated || retry) && (
          <button type="button" className="btn btn-sm" onClick={onReview} disabled={!canReview || !outcome}>
            {outdated ? f.reviewCurrent : f.reviewRetry}
          </button>
        )}
      </div>
      <p className="hint" role="status">
        {status}
      </p>
      {findings.length > 0 && (
        <ul className="usecase-review-findings">
          {findings.map((finding, index) => (
            <li key={index}>
              <strong>
                {finding.disposition === 'confirm' ? f.reviewConfirm : findingLabels[finding.kind]} · {finding.message}
              </strong>
              <p>{f.reviewEvidence(finding.evidence)}</p>
              <p>{finding.suggestion}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

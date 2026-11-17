import type { UseCaseDraft } from '../types'

interface Props {
  useCase: UseCaseDraft
  index: number
  locatedId?: string
  linkCount: number
  onChange: (next: UseCaseDraft) => void
  onRemove: () => void
}

export default function UseCaseCard({ useCase, index, locatedId, linkCount, onChange, onRemove }: Props) {
  return (
    <article
      id={`spec-${useCase.id}`}
      tabIndex={-1}
      className={`card${locatedId === useCase.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">用例 {index + 1}</span>
        {linkCount > 0 && <span className="badge badge-quiet">被 {linkCount} 个参与者使用</span>}
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title="删除这个用例"
          aria-label={`删除用例 ${useCase.name || index + 1}`}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">用例名</span>
        <input
          className="input"
          value={useCase.name}
          placeholder="如：借书"
          onChange={(event) => onChange({ ...useCase, name: event.target.value })}
          data-testid={`usecase-name-${index}`}
        />
      </label>
    </article>
  )
}

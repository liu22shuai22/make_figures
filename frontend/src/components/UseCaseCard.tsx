import type { UseCaseDraft } from '../types'
import { useLocale } from '../LocaleContext'

interface Props {
  useCase: UseCaseDraft
  index: number
  locatedId?: string
  linkCount: number
  onChange: (next: UseCaseDraft) => void
  onRemove: () => void
}

export default function UseCaseCard({ useCase, index, locatedId, linkCount, onChange, onRemove }: Props) {
  const { app } = useLocale()
  const f = app.form

  return (
    <article
      id={`spec-${useCase.id}`}
      tabIndex={-1}
      className={`card${locatedId === useCase.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">{f.useCaseN(index + 1)}</span>
        {linkCount > 0 && <span className="badge badge-quiet">{f.useCaseActors(linkCount)}</span>}
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title={f.delUseCase}
          aria-label={f.delUseCaseAria(useCase.name || index + 1)}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">{f.useCaseName}</span>
        <input
          className="input"
          value={useCase.name}
          placeholder={f.useCasePh}
          onChange={(event) => onChange({ ...useCase, name: event.target.value })}
          data-testid={`usecase-name-${index}`}
        />
      </label>
    </article>
  )
}

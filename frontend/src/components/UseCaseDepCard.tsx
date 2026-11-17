import type { UseCaseDepDraft, UseCaseDepKind, UseCaseDraft } from '../types'
import { useLocale } from '../LocaleContext'

interface Props {
  dep: UseCaseDepDraft
  index: number
  locatedId?: string
  useCases: UseCaseDraft[]
  onChange: (next: UseCaseDepDraft) => void
  onRemove: () => void
}

export default function UseCaseDepCard({
  dep,
  index,
  locatedId,
  useCases,
  onChange,
  onRemove,
}: Props) {
  const { app } = useLocale()
  const f = app.form
  const kinds: { value: UseCaseDepKind; label: string }[] = [
    { value: 'include', label: f.include },
    { value: 'extend', label: f.extend },
    { value: 'generalize', label: f.generalize },
  ]
  const fromHint =
    dep.kind === 'generalize' ? f.childUc : dep.kind === 'include' ? f.baseUc : f.extendingUc
  const toHint =
    dep.kind === 'generalize' ? f.parentUc : dep.kind === 'include' ? f.includedUc : f.extendedUc

  return (
    <article
      id={`spec-${dep.id}`}
      tabIndex={-1}
      className={`card${locatedId === dep.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">{f.depN(index + 1)}</span>
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title={f.delDep}
          aria-label={f.delDepAria(index + 1)}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">{f.depKind}</span>
        <select
          className="input"
          value={dep.kind}
          onChange={(event) => onChange({ ...dep, kind: event.target.value as UseCaseDepKind })}
          data-testid={`ucdep-kind-${index}`}
        >
          {kinds.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>

      <div className="field-row">
        <label className="field">
          <span className="field-label">{fromHint}</span>
          <select
            className="input"
            value={dep.fromId}
            onChange={(event) => onChange({ ...dep, fromId: event.target.value })}
            data-testid={`ucdep-from-${index}`}
          >
            <option value="">{f.pickUseCase}</option>
            {useCases.map((item) => (
              <option key={item.id} value={item.id} disabled={item.id === dep.toId}>
                {item.name.trim() || f.unnamed}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{toHint}</span>
          <select
            className="input"
            value={dep.toId}
            onChange={(event) => onChange({ ...dep, toId: event.target.value })}
            data-testid={`ucdep-to-${index}`}
          >
            <option value="">{f.pickUseCase}</option>
            {useCases.map((item) => (
              <option key={item.id} value={item.id} disabled={item.id === dep.fromId}>
                {item.name.trim() || f.unnamed}
              </option>
            ))}
          </select>
        </label>
      </div>
    </article>
  )
}

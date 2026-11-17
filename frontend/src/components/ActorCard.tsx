import type { ActorDraft, ActorKind } from '../types'
import { useLocale } from '../LocaleContext'

interface Props {
  actor: ActorDraft
  index: number
  locatedId?: string
  linkCount: number
  onChange: (next: ActorDraft) => void
  onRemove: () => void
}

export default function ActorCard({ actor, index, locatedId, linkCount, onChange, onRemove }: Props) {
  const { app } = useLocale()
  const f = app.form

  return (
    <article
      id={`spec-${actor.id}`}
      tabIndex={-1}
      className={`card${locatedId === actor.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">{f.actorN(index + 1)}</span>
        {linkCount > 0 && <span className="badge badge-quiet">{f.actorLinks(linkCount)}</span>}
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title={f.delActor}
          aria-label={f.delActorAria(actor.name || index + 1)}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">{f.name}</span>
        <input
          className="input"
          value={actor.name}
          placeholder={f.actorPh}
          onChange={(event) => onChange({ ...actor, name: event.target.value })}
          data-testid={`actor-name-${index}`}
        />
      </label>

      <label className="field">
        <span className="field-label">{f.role}</span>
        <select
          className="input"
          value={actor.kind}
          onChange={(event) => onChange({ ...actor, kind: event.target.value as ActorKind })}
          data-testid={`actor-kind-${index}`}
        >
          <option value="primary">{f.rolePrimary}</option>
          <option value="secondary">{f.roleSecondary}</option>
        </select>
      </label>
    </article>
  )
}

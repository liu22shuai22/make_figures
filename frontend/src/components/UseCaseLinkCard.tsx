import type { ActorDraft, UseCaseDraft, UseCaseLinkDraft } from '../types'
import { useLocale } from '../LocaleContext'

interface Props {
  link: UseCaseLinkDraft
  index: number
  locatedId?: string
  actors: ActorDraft[]
  useCases: UseCaseDraft[]
  onChange: (next: UseCaseLinkDraft) => void
  onRemove: () => void
}

export default function UseCaseLinkCard({
  link,
  index,
  locatedId,
  actors,
  useCases,
  onChange,
  onRemove,
}: Props) {
  const { app } = useLocale()
  const f = app.form

  return (
    <article
      id={`spec-${link.id}`}
      tabIndex={-1}
      className={`card${locatedId === link.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">{f.linkN(index + 1)}</span>
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title={f.delLink}
          aria-label={f.delLinkAria(index + 1)}
        >
          ×
        </button>
      </div>

      <div className="field-row">
        <label className="field">
          <span className="field-label">{app.actors}</span>
          <select
            className="input"
            value={link.actorId}
            onChange={(event) => onChange({ ...link, actorId: event.target.value })}
            data-testid={`uclink-actor-${index}`}
          >
            <option value="">{f.pickActor}</option>
            {actors.map((actor) => (
              <option key={actor.id} value={actor.id}>
                {actor.name.trim() || f.unnamed}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">{app.useCases}</span>
          <select
            className="input"
            value={link.useCaseId}
            onChange={(event) => onChange({ ...link, useCaseId: event.target.value })}
            data-testid={`uclink-usecase-${index}`}
          >
            <option value="">{f.pickUseCase}</option>
            {useCases.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name.trim() || f.unnamed}
              </option>
            ))}
          </select>
        </label>
      </div>
    </article>
  )
}

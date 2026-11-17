import type { ActorDraft, UseCaseDraft, UseCaseLinkDraft } from '../types'

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
  return (
    <article
      id={`spec-${link.id}`}
      tabIndex={-1}
      className={`card${locatedId === link.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">关联 {index + 1}</span>
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title="删除这条关联"
          aria-label={`删除关联 ${index + 1}`}
        >
          ×
        </button>
      </div>

      <div className="field-row">
        <label className="field">
          <span className="field-label">参与者</span>
          <select
            className="input"
            value={link.actorId}
            onChange={(event) => onChange({ ...link, actorId: event.target.value })}
            data-testid={`uclink-actor-${index}`}
          >
            <option value="">选择参与者</option>
            {actors.map((actor) => (
              <option key={actor.id} value={actor.id}>
                {actor.name.trim() || '（未命名）'}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">用例</span>
          <select
            className="input"
            value={link.useCaseId}
            onChange={(event) => onChange({ ...link, useCaseId: event.target.value })}
            data-testid={`uclink-usecase-${index}`}
          >
            <option value="">选择用例</option>
            {useCases.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name.trim() || '（未命名）'}
              </option>
            ))}
          </select>
        </label>
      </div>
    </article>
  )
}

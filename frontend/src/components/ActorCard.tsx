import type { ActorDraft, ActorKind } from '../types'

interface Props {
  actor: ActorDraft
  index: number
  locatedId?: string
  linkCount: number
  onChange: (next: ActorDraft) => void
  onRemove: () => void
}

export default function ActorCard({ actor, index, locatedId, linkCount, onChange, onRemove }: Props) {
  return (
    <article
      id={`spec-${actor.id}`}
      tabIndex={-1}
      className={`card${locatedId === actor.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">参与者 {index + 1}</span>
        {linkCount > 0 && <span className="badge badge-quiet">连 {linkCount} 个用例</span>}
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title="删除这个参与者"
          aria-label={`删除参与者 ${actor.name || index + 1}`}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">名称</span>
        <input
          className="input"
          value={actor.name}
          placeholder="如：读者"
          onChange={(event) => onChange({ ...actor, name: event.target.value })}
          data-testid={`actor-name-${index}`}
        />
      </label>

      <label className="field">
        <span className="field-label">角色</span>
        <select
          className="input"
          value={actor.kind}
          onChange={(event) => onChange({ ...actor, kind: event.target.value as ActorKind })}
          data-testid={`actor-kind-${index}`}
        >
          <option value="primary">主要参与者</option>
          <option value="secondary">次要参与者</option>
        </select>
      </label>
    </article>
  )
}

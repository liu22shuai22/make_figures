import { CARDINALITIES } from '../types'
import type { AttrDraft, Cardinality, EndDraft, EntityDraft, RelationDraft } from '../types'
import { newAttr } from '../spec'
import { useLocale } from '../LocaleContext'

interface RelationCardProps {
  relation: RelationDraft
  index: number
  locatedId?: string
  entities: EntityDraft[]
  onChange: (next: RelationDraft) => void
  onRemove: () => void
}

export default function RelationCard({ relation, index, locatedId, entities, onChange, onRemove }: RelationCardProps) {
  const { app } = useLocale()
  const f = app.form
  const isSelf =
    relation.ends.length === 2 &&
    relation.ends[0].entityId !== '' &&
    relation.ends[0].entityId === relation.ends[1].entityId
  const isTernary = relation.ends.length === 3

  const patchEnd = (endIndex: number, patch: Partial<EndDraft>) => {
    onChange({
      ...relation,
      ends: relation.ends.map((end, current) => (current === endIndex ? { ...end, ...patch } : end)),
    })
  }

  const addThirdEnd = () => {
    // 默认挑一个还没用过的实体，避免一上手就是「三个端点必须不同」的错误
    const used = new Set(relation.ends.map((end) => end.entityId))
    const candidate = entities.find((entity) => !used.has(entity.id))
    onChange({ ...relation, ends: [...relation.ends, { entityId: candidate?.id ?? '', card: 'p' }] })
  }

  const removeThirdEnd = () => {
    onChange({ ...relation, ends: relation.ends.slice(0, 2) })
  }

  const patchAttr = (attrId: string, patch: Partial<AttrDraft>) => {
    onChange({
      ...relation,
      attrs: relation.attrs.map((attr) => (attr.id === attrId ? { ...attr, ...patch } : attr)),
    })
  }

  const addAttr = () => onChange({ ...relation, attrs: [...relation.attrs, newAttr('')] })
  const removeAttr = (attrId: string) =>
    onChange({ ...relation, attrs: relation.attrs.filter((attr) => attr.id !== attrId) })

  return (
    <article id={`spec-${relation.id}`} tabIndex={-1} className={`card${locatedId === relation.id ? ' spec-located' : ''}`}>
      <div className="card-head">
        <span className="card-index">{f.relationN(index + 1)}</span>
        {isSelf && <span className="badge badge-quiet">{f.selfRel}</span>}
        {isTernary && <span className="badge badge-quiet">{f.ternary}</span>}
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title={f.delRelation}
          aria-label={f.delRelationAria(relation.name || index + 1)}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">{f.relationName}</span>
        <input
          className="input"
          value={relation.name}
          placeholder={f.relationPh}
          onChange={(event) => onChange({ ...relation, name: event.target.value })}
          data-testid={`relation-name-${index}`}
        />
      </label>

      <div className="subhead">
        <span className="subhead-title">{f.endsTitle}</span>
        {isTernary ? (
          <button type="button" className="link-btn" onClick={removeThirdEnd}>
            {f.removeThird}
          </button>
        ) : (
          <button type="button" className="link-btn" onClick={addThirdEnd} disabled={entities.length < 3}>
            {f.addThird}
          </button>
        )}
      </div>

      <div className="ends">
        {relation.ends.map((end, endIndex) => (
          <div className="end-row" key={endIndex}>
            <span className="end-index">{endIndex + 1}</span>
            <select
              className="input"
              value={end.entityId}
              onChange={(event) => patchEnd(endIndex, { entityId: event.target.value, missingName: undefined })}
              aria-label={f.endEntityAria(relation.name || index + 1, endIndex + 1)}
              data-testid={`relation-end-entity-${index}-${endIndex}`}
            >
              <option value="">{f.pickEntity}</option>
              {end.missingName && (
                <option value="" disabled>
                  {f.missingEntity(end.missingName)}
                </option>
              )}
              {entities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.name.trim() || f.unnamedEntity}
                </option>
              ))}
            </select>
            <select
              className="input card-select"
              value={end.card}
              onChange={(event) => patchEnd(endIndex, { card: event.target.value as Cardinality })}
              aria-label={f.endCardAria(relation.name || index + 1, endIndex + 1)}
              data-testid={`relation-end-card-${index}-${endIndex}`}
            >
              {CARDINALITIES.map((card) => (
                <option key={card.value} value={card.value}>
                  {card.label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div className="subhead">
        <span className="subhead-title">{f.relAttrs(relation.attrs.length)}</span>
        <button type="button" className="link-btn" onClick={addAttr} data-testid={`relation-add-attr-${index}`}>
          {f.addRelAttr}
        </button>
      </div>

      {relation.attrs.length === 0 ? (
        <p className="hint">{f.relAttrHint}</p>
      ) : (
        <ul className="attr-list">
          {relation.attrs.map((attr, attrIndex) => (
            <li id={`spec-${attr.id}`} tabIndex={-1} className={`attr-row${locatedId === attr.id ? ' spec-located' : ''}`} key={attr.id}>
              <span className="attr-dot" aria-hidden="true" />
              <input
                className="input input-flat"
                value={attr.name}
                placeholder={f.relAttrName}
                onChange={(event) => patchAttr(attr.id, { name: event.target.value })}
                data-testid={`relation-attr-${index}-${attrIndex}`}
              />
              <button
                type="button"
                className="icon-btn"
                onClick={() => removeAttr(attr.id)}
                title={f.delRelAttr}
                aria-label={f.delRelAttrAria(attr.name || attrIndex + 1)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}

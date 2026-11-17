import type { AttrDraft, EntityDraft } from '../types'
import { newAttr } from '../spec'
import { useLocale } from '../LocaleContext'

interface EntityCardProps {
  entity: EntityDraft
  index: number
  locatedId?: string
  /** 有多少条联系引用这个实体，删除时提示用 */
  relationCount: number
  onChange: (next: EntityDraft) => void
  onRemove: () => void
}

export default function EntityCard({ entity, index, locatedId, relationCount, onChange, onRemove }: EntityCardProps) {
  const { app } = useLocale()
  const f = app.form

  const patchAttr = (attrId: string, patch: Partial<AttrDraft>) => {
    onChange({
      ...entity,
      attrs: entity.attrs.map((attr) => (attr.id === attrId ? { ...attr, ...patch } : attr)),
    })
  }

  const removeAttr = (attrId: string) => {
    onChange({ ...entity, attrs: entity.attrs.filter((attr) => attr.id !== attrId) })
  }

  /**
   * 允许直接输入 "*学号" 的写法：识别到前导星号就自动转成主键标记，
   * 避免把星号带进属性名（后端会把 * 剥掉，导致编辑器和图片对不上）。
   */
  const typeAttrName = (attrId: string, raw: string) => {
    if (raw.startsWith('*')) {
      patchAttr(attrId, { name: raw.replace(/^\*+/, '').trimStart(), pk: true })
    } else {
      patchAttr(attrId, { name: raw })
    }
  }

  return (
    <article id={`spec-${entity.id}`} tabIndex={-1} className={`card${locatedId === entity.id ? ' spec-located' : ''}`}>
      <div className="card-head">
        <span className="card-index">{f.entityN(index + 1)}</span>
        {relationCount > 0 && <span className="badge badge-quiet">{f.entityRefs(relationCount)}</span>}
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title={f.delEntity}
          aria-label={f.delEntityAria(entity.name || index + 1)}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">{f.entityName}</span>
        <input
          className="input"
          value={entity.name}
          placeholder={f.entityPh}
          onChange={(event) => onChange({ ...entity, name: event.target.value })}
          data-testid={`entity-name-${index}`}
        />
      </label>

      <div className="subhead">
        <span className="subhead-title">{f.attrsCount(entity.attrs.length)}</span>
        <button
          type="button"
          className="link-btn"
          onClick={() => onChange({ ...entity, attrs: [...entity.attrs, newAttr('')] })}
          data-testid={`entity-add-attr-${index}`}
        >
          {f.addAttr}
        </button>
      </div>

      {entity.attrs.length === 0 ? (
        <p className="hint">{f.attrHint}</p>
      ) : (
        <ul className="attr-list">
          {entity.attrs.map((attr, attrIndex) => (
            <li id={`spec-${attr.id}`} tabIndex={-1} className={`attr-row${locatedId === attr.id ? ' spec-located' : ''}`} key={attr.id}>
              <input
                type="checkbox"
                className="checkbox"
                checked={attr.pk}
                onChange={(event) => patchAttr(attr.id, { pk: event.target.checked })}
                title={f.markPk}
                aria-label={f.attrPkAria(attrIndex + 1)}
              />
              <input
                className="input input-flat"
                value={attr.name}
                placeholder={f.attrName}
                onChange={(event) => typeAttrName(attr.id, event.target.value)}
                data-testid={`entity-attr-${index}-${attrIndex}`}
              />
              <button
                type="button"
                className="icon-btn"
                onClick={() => removeAttr(attr.id)}
                title={f.delAttr}
                aria-label={f.delAttrAria(attr.name || attrIndex + 1)}
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

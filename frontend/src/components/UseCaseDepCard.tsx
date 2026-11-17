import type { UseCaseDepDraft, UseCaseDepKind, UseCaseDraft } from '../types'

const DEP_KINDS: { value: UseCaseDepKind; label: string }[] = [
  { value: 'include', label: '«include» 包含' },
  { value: 'extend', label: '«extend» 扩展' },
  { value: 'generalize', label: '泛化（继承）' },
]

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
  const fromHint =
    dep.kind === 'generalize' ? '子用例' : dep.kind === 'include' ? '基用例' : '扩展用例'
  const toHint =
    dep.kind === 'generalize' ? '父用例' : dep.kind === 'include' ? '被包含用例' : '被扩展用例'

  return (
    <article
      id={`spec-${dep.id}`}
      tabIndex={-1}
      className={`card${locatedId === dep.id ? ' spec-located' : ''}`}
    >
      <div className="card-head">
        <span className="card-index">依赖 {index + 1}</span>
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          onClick={onRemove}
          title="删除这条依赖"
          aria-label={`删除依赖 ${index + 1}`}
        >
          ×
        </button>
      </div>

      <label className="field">
        <span className="field-label">关系类型</span>
        <select
          className="input"
          value={dep.kind}
          onChange={(event) => onChange({ ...dep, kind: event.target.value as UseCaseDepKind })}
          data-testid={`ucdep-kind-${index}`}
        >
          {DEP_KINDS.map((item) => (
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
            <option value="">选择用例</option>
            {useCases.map((item) => (
              <option key={item.id} value={item.id} disabled={item.id === dep.toId}>
                {item.name.trim() || '（未命名）'}
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
            <option value="">选择用例</option>
            {useCases.map((item) => (
              <option key={item.id} value={item.id} disabled={item.id === dep.fromId}>
                {item.name.trim() || '（未命名）'}
              </option>
            ))}
          </select>
        </label>
      </div>
    </article>
  )
}

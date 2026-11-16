import { useEffect, useId, useRef, useState } from 'react'
import type { SpecDraft } from '../types'

interface SearchResult {
  id: string
  name: string
  context: string
}

const normalize = (text: string) => text.normalize('NFKC').trim().toLowerCase()

function findResults(spec: SpecDraft, query: string): SearchResult[] {
  const term = normalize(query)
  if (!term) return []
  const entities = new Map(spec.entities.map((entity) => [entity.id, entity.name.trim()]))
  const entries = [
    ...spec.entities.flatMap((entity, index) => [
      { id: entity.id, name: entity.name, context: `实体 ${index + 1}` },
      ...entity.attrs.map((attr) => ({ id: attr.id, name: attr.name,
        context: `实体属性 · ${entity.name.trim() || `实体 ${index + 1}`}` })),
    ]),
    ...spec.relations.flatMap((relation, index) => {
      const endpoints = relation.ends.map((end) => entities.get(end.entityId)).filter(Boolean).join(' — ')
      const context = `联系 ${index + 1}${endpoints ? ` · ${endpoints}` : ''}`
      return [
        { id: relation.id, name: relation.name, context },
        ...relation.attrs.map((attr) => ({ id: attr.id, name: attr.name,
          context: `联系属性 · ${relation.name.trim() || `联系 ${index + 1}`}${endpoints ? ` · ${endpoints}` : ''}` })),
      ]
    }),
  ]
  return entries.map((entry) => ({ entry, name: normalize(entry.name) }))
    .filter(({ name }) => name.includes(term))
    .sort((a, b) => rank(a.name, term) - rank(b.name, term))
    .map(({ entry }) => entry)
}

function rank(name: string, term: string) {
  return name === term ? 0 : name.startsWith(term) ? 1 : 2
}

export default function SpecSearch({ spec, onSelect }: { spec: SpecDraft; onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const button = useRef<HTMLButtonElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const panelId = useId()
  const results = open ? findResults(spec, query) : []

  useEffect(() => {
    if (open) {
      input.current?.focus()
      input.current?.select()
    }
  }, [open])

  const select = (id: string) => {
    setOpen(false)
    onSelect(id)
  }

  return (
    <div className="spec-search" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
    }} onKeyDown={(event) => {
      if (open && event.key === 'Escape' && !event.nativeEvent.isComposing) {
        event.preventDefault()
        setOpen(false)
        button.current?.focus()
      }
    }}>
      <button ref={button} className="icon-btn spec-search-trigger" type="button" title="搜索规格"
        aria-label="搜索规格" aria-expanded={open} aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((previous) => !previous)}>
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="10.5" cy="10.5" r="6" />
          <path d="m15 15 5 5" />
        </svg>
      </button>
      {open && (
        <div id={panelId} className="spec-search-popover">
          <input ref={input} type="search" className="input" aria-label="搜索实体、属性或联系"
            placeholder="搜索实体、属性或联系…" value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing && results[0]) {
                event.preventDefault()
                select(results[0].id)
              }
            }} />
          <p className="spec-search-status" role="status">
            {!query.trim() ? '输入名称以定位左侧规格' : results.length ? `${results.length} 条结果` : '没有找到匹配项'}
          </p>
          {results.length > 0 && (
            <ul className="spec-search-results">
              {results.map((result) => (
                <li key={result.id}>
                  <button type="button" className="spec-search-result" onClick={() => select(result.id)}>
                    <strong>{result.name.trim()}</strong>
                    <span>{result.context}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

import { useEffect, useId, useRef, useState } from 'react'
import type { SpecDraft } from '../types'
import { useLocale } from '../LocaleContext'
import type { AppCopy } from '../appLocale'

interface SearchResult {
  id: string
  name: string
  context: string
}

const normalize = (text: string) => text.normalize('NFKC').trim().toLowerCase()

function findResults(spec: SpecDraft, query: string, f: AppCopy['form']): SearchResult[] {
  const term = normalize(query)
  if (!term) return []
  const entities = new Map(spec.entities.map((entity) => [entity.id, entity.name.trim()]))
  const entries = [
    ...spec.entities.flatMap((entity, index) => [
      { id: entity.id, name: entity.name, context: f.searchEntity(index + 1) },
      ...entity.attrs.map((attr) => ({
        id: attr.id,
        name: attr.name,
        context: f.searchEntityAttr(entity.name.trim() || f.searchEntity(index + 1)),
      })),
    ]),
    ...spec.relations.flatMap((relation, index) => {
      const endpoints = relation.ends.map((end) => entities.get(end.entityId)).filter(Boolean).join(' — ')
      const context = `${f.searchRelation(index + 1)}${endpoints ? ` · ${endpoints}` : ''}`
      return [
        { id: relation.id, name: relation.name, context },
        ...relation.attrs.map((attr) => ({
          id: attr.id,
          name: attr.name,
          context: `${f.searchRelAttr(relation.name.trim() || f.searchRelation(index + 1))}${endpoints ? ` · ${endpoints}` : ''}`,
        })),
      ]
    }),
  ]
  return entries
    .map((entry) => ({ entry, name: normalize(entry.name) }))
    .filter(({ name }) => name.includes(term))
    .sort((a, b) => rank(a.name, term) - rank(b.name, term))
    .map(({ entry }) => entry)
}

function rank(name: string, term: string) {
  return name === term ? 0 : name.startsWith(term) ? 1 : 2
}

export default function SpecSearch({ spec, onSelect }: { spec: SpecDraft; onSelect: (id: string) => void }) {
  const { app } = useLocale()
  const f = app.form
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const button = useRef<HTMLButtonElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const panelId = useId()
  const results = open ? findResults(spec, query, f) : []

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
    <div
      className="spec-search"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
      }}
      onKeyDown={(event) => {
        if (open && event.key === 'Escape' && !event.nativeEvent.isComposing) {
          event.preventDefault()
          setOpen(false)
          button.current?.focus()
        }
      }}
    >
      <button
        ref={button}
        className="icon-btn spec-search-trigger"
        type="button"
        title={f.searchTitle}
        aria-label={f.searchTitle}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((previous) => !previous)}
      >
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <circle cx="10.5" cy="10.5" r="6" />
          <path d="m15 15 5 5" />
        </svg>
      </button>
      {open && (
        <div id={panelId} className="spec-search-popover">
          <input
            ref={input}
            type="search"
            className="input"
            aria-label={f.searchAria}
            placeholder={f.searchPh}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing && results[0]) {
                event.preventDefault()
                select(results[0].id)
              }
            }}
          />
          <p className="spec-search-status" role="status">
            {!query.trim() ? f.searchHint : results.length ? f.searchCount(results.length) : f.searchEmpty}
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

import type { SpecDraft } from './types'

export function proposeSingleCardinality(spec: SpecDraft, request: string) {
  const text = request.trim().replace(/^(?:请\s*)?(?:帮我\s*)?(?:把\s*|改成\s*|改为\s*)?/, '')
    .replace(/[。！!。]$/, '').trim()
  const match = /^(?:每个|一个|一名)?(.+?)(?:只能|仅能|最多(?:可以|能)?)(.+?)(?:一|1)\s*(?:门|个|名|位|项|件|本|张|条|份)?\s*(.+)$/.exec(text)
  if (!match) return undefined
  const [, subject, verb, object] = match.map((part) => part.trim())
  const source = spec.entities.find(({ name }) => name.trim() === subject)
  const target = spec.entities.find(({ name }) => name.trim() === object)
  if (!source || !target || source.id === target.id) return undefined
  const matching = spec.relations.filter(({ ends }) => ends.length === 2 &&
    ends.some(({ entityId }) => entityId === source.id) && ends.some(({ entityId }) => entityId === target.id))
  const named = matching.filter(({ name }) => name.trim() === verb)
  const relation = named.length === 1 ? named[0] :
    matching.length === 1 && /^(?:选择|选|选课|选修|关联|拥有|属于|对应|管理|分配|绑定|借阅)$/.test(verb)
      ? matching[0] : undefined
  if (!relation) return undefined
  const end = relation.ends.find(({ entityId }) => entityId === target.id)
  if (!end) return undefined
  return {
    source: spec,
    relationId: relation.id,
    relation: relation.name,
    target: target.name,
    previous: end.card,
    draft: {
      ...spec,
      relations: spec.relations.map((item) => item.id === relation.id
        ? { ...item, ends: item.ends.map((endpoint) => endpoint === end ? { ...endpoint, card: '1' as const } : endpoint) }
        : item),
    },
  }
}

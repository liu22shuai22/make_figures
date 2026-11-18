import type { Cardinality, SpecDraft } from './types'

export interface CardinalityChoice {
  relationIndex: number
  endpointIndex: number
  card: Cardinality
}
export function buildCardinalityProposal(spec: SpecDraft, choice: CardinalityChoice) {
  const { relationIndex, endpointIndex, card } = choice
  const relation = spec.relations[relationIndex]
  if (relation?.ends.length !== 2 || relation.ends[0].entityId === relation.ends[1].entityId) return undefined
  const end = relation.ends[endpointIndex]
  const target = end && spec.entities.find(({ id }) => id === end.entityId)
  if (!end || !target) return undefined
  return {
    source: spec,
    relationIndex,
    relation: relation.name.trim() || '关联',
    target: target.name,
    previous: end.card,
    card,
    draft: {
      ...spec,
      relations: spec.relations.map((item, index) => index === relationIndex
        ? { ...item, ends: item.ends.map((endpoint, i) => i === endpointIndex ? { ...endpoint, card } : endpoint) }
        : item),
    },
  }
}

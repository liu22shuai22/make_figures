import type {
  ActorDraft,
  ActorKind,
  UseCaseDepDraft,
  UseCaseDepKind,
  UseCaseDraft,
  UseCaseJsonSpec,
  UseCaseLinkDraft,
  UseCaseSpecDraft,
} from './types'

export const USECASE_LIMITS = {
  actors: 12,
  useCases: 24,
  links: 48,
  dependencies: 48,
  label: 24,
} as const

let seq = 0
const uid = (prefix: string) => `${prefix}-${++seq}`

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const toText = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

const charLength = (text: string) => Array.from(text).length

function parseActorKind(value: unknown): ActorKind {
  const raw = toText(value).toLowerCase()
  if (raw === 'secondary' || raw === '次' || raw === '次要') return 'secondary'
  return 'primary'
}

function parseDepKind(value: unknown): UseCaseDepKind | null {
  const raw = toText(value).toLowerCase()
  if (raw === 'include' || raw === '包含' || raw === '<<include>>' || raw === '«include»') return 'include'
  if (raw === 'extend' || raw === '扩展' || raw === '<<extend>>' || raw === '«extend»') return 'extend'
  if (
    raw === 'generalize' ||
    raw === 'generalisation' ||
    raw === 'generalization' ||
    raw === '泛化' ||
    raw === '继承'
  ) {
    return 'generalize'
  }
  return null
}

export const EMPTY_USECASE_SPEC: UseCaseSpecDraft = {
  title: '',
  system: '',
  actors: [],
  useCases: [],
  links: [],
  dependencies: [],
}

export function uniqueName(base: string, taken: string[]): string {
  if (!taken.includes(base)) return base
  let index = 2
  while (taken.includes(`${base}${index}`)) index += 1
  return `${base}${index}`
}

export const newActor = (name: string, kind: ActorKind = 'primary'): ActorDraft => ({
  id: uid('actor'),
  name,
  kind,
})

export const newUseCase = (name: string): UseCaseDraft => ({
  id: uid('usecase'),
  name,
})

export const newUseCaseLink = (actorId: string, useCaseId: string): UseCaseLinkDraft => ({
  id: uid('uclink'),
  actorId,
  useCaseId,
})

export const newUseCaseDep = (
  kind: UseCaseDepKind,
  fromId: string,
  toId: string,
): UseCaseDepDraft => ({
  id: uid('ucdep'),
  kind,
  fromId,
  toId,
})

type ParseOutcome =
  | { ok: true; spec: UseCaseSpecDraft; notices: string[] }
  | { ok: false; error: string }

/**
 * 把用例图 JSON 转成可编辑草稿。
 * 兼容 actors / useCases / use_cases、links / dependencies 里用名字引用。
 */
export function parseUseCaseSpec(raw: unknown): ParseOutcome {
  if (!isObject(raw)) {
    return {
      ok: false,
      error: 'JSON 顶层必须是对象，形如 { "title": "…", "actors": [...], "useCases": [...], "links": [...] }。',
    }
  }

  const notices: string[] = []
  const actorsRaw = raw.actors
  const useCasesRaw = raw.useCases ?? raw.use_cases
  if (!Array.isArray(actorsRaw)) {
    return { ok: false, error: '缺少 actors 数组（用例图至少要有一个参与者）。' }
  }
  if (!Array.isArray(useCasesRaw)) {
    return { ok: false, error: '缺少 useCases 数组（用例图至少要有一个用例）。' }
  }

  const actors: ActorDraft[] = []
  const actorByName = new Map<string, string>()
  for (const item of actorsRaw) {
    if (!isObject(item) && typeof item !== 'string' && typeof item !== 'number') {
      notices.push('忽略了无法识别的参与者条目。')
      continue
    }
    const name = isObject(item) ? toText(item.name) : toText(item)
    if (!name) continue
    if (actorByName.has(name)) {
      notices.push(`参与者「${name}」重复，已去重。`)
      continue
    }
    const actor = newActor(name, isObject(item) ? parseActorKind(item.kind) : 'primary')
    actors.push(actor)
    actorByName.set(name, actor.id)
  }

  const useCases: UseCaseDraft[] = []
  const useCaseByName = new Map<string, string>()
  for (const item of useCasesRaw) {
    if (!isObject(item) && typeof item !== 'string' && typeof item !== 'number') {
      notices.push('忽略了无法识别的用例条目。')
      continue
    }
    const name = isObject(item) ? toText(item.name) : toText(item)
    if (!name) continue
    if (useCaseByName.has(name)) {
      notices.push(`用例「${name}」重复，已去重。`)
      continue
    }
    if (actorByName.has(name)) {
      notices.push(`用例「${name}」与参与者重名，已跳过（拖拽布局需要全局唯一名称）。`)
      continue
    }
    const useCase = newUseCase(name)
    useCases.push(useCase)
    useCaseByName.set(name, useCase.id)
  }

  if (!actors.length) return { ok: false, error: 'actors 为空，请至少保留一个参与者。' }
  if (!useCases.length) return { ok: false, error: 'useCases 为空，请至少保留一个用例。' }

  const links: UseCaseLinkDraft[] = []
  const linkKeys = new Set<string>()
  const linksRaw = raw.links
  if (linksRaw !== undefined && linksRaw !== null && !Array.isArray(linksRaw)) {
    notices.push('links 不是数组，已忽略全部关联。')
  } else if (Array.isArray(linksRaw)) {
    for (const item of linksRaw) {
      if (!isObject(item)) {
        notices.push('忽略了无法识别的关联条目。')
        continue
      }
      const actorName = toText(item.actor ?? item.actorName)
      const useCaseName = toText(item.useCase ?? item.usecase ?? item.use_case)
      const actorId = actorByName.get(actorName)
      const useCaseId = useCaseByName.get(useCaseName)
      if (!actorId || !useCaseId) {
        notices.push(
          `关联「${actorName || '?'} → ${useCaseName || '?'}」引用了不存在的参与者或用例，已跳过。`,
        )
        continue
      }
      const key = `${actorId}::${useCaseId}`
      if (linkKeys.has(key)) {
        notices.push(`关联「${actorName} → ${useCaseName}」重复，已去重。`)
        continue
      }
      linkKeys.add(key)
      links.push(newUseCaseLink(actorId, useCaseId))
    }
  }

  const dependencies: UseCaseDepDraft[] = []
  const depKeys = new Set<string>()
  const depsRaw = raw.dependencies ?? raw.deps ?? raw.relations
  if (depsRaw !== undefined && depsRaw !== null && !Array.isArray(depsRaw)) {
    notices.push('dependencies 不是数组，已忽略全部依赖。')
  } else if (Array.isArray(depsRaw)) {
    for (const item of depsRaw) {
      if (!isObject(item)) {
        notices.push('忽略了无法识别的依赖条目。')
        continue
      }
      const kind = parseDepKind(item.kind ?? item.type ?? item.relation)
      if (!kind) {
        notices.push('忽略了未知类型的依赖（仅支持 include / extend / generalize）。')
        continue
      }
      const fromName = toText(item.from ?? item.source ?? item.base)
      const toName = toText(item.to ?? item.target ?? item.inclusion ?? item.parent)
      const fromId = useCaseByName.get(fromName)
      const toId = useCaseByName.get(toName)
      if (!fromId || !toId) {
        notices.push(
          `依赖「${fromName || '?'} → ${toName || '?'}」引用了不存在的用例，已跳过。`,
        )
        continue
      }
      if (fromId === toId) {
        notices.push(`依赖「${fromName}」指向自身，已跳过。`)
        continue
      }
      const key = `${kind}::${fromId}::${toId}`
      if (depKeys.has(key)) {
        notices.push(`依赖「${kind}: ${fromName} → ${toName}」重复，已去重。`)
        continue
      }
      depKeys.add(key)
      dependencies.push(newUseCaseDep(kind, fromId, toId))
    }
  }

  const system = toText(raw.system) || toText(raw.title) || '系统'
  const title = toText(raw.title)

  return {
    ok: true,
    spec: { title, system, actors, useCases, links, dependencies },
    notices,
  }
}

export function toUseCaseJson(
  spec: UseCaseSpecDraft,
  positions?: Record<string, [number, number]>,
): UseCaseJsonSpec {
  const actorName = new Map(spec.actors.map((actor) => [actor.id, actor.name.trim()]))
  const useCaseName = new Map(spec.useCases.map((item) => [item.id, item.name.trim()]))
  const payload: UseCaseJsonSpec = {
    kind: 'usecase',
    title: spec.title.trim(),
    system: spec.system.trim() || spec.title.trim() || '系统',
    actors: spec.actors.map((actor) => ({
      name: actor.name.trim(),
      kind: actor.kind,
    })),
    useCases: spec.useCases.map((item) => ({ name: item.name.trim() })),
    links: spec.links
      .map((link) => ({
        actor: actorName.get(link.actorId) || '',
        useCase: useCaseName.get(link.useCaseId) || '',
      }))
      .filter((link) => link.actor && link.useCase),
    dependencies: spec.dependencies
      .map((dep) => ({
        kind: dep.kind,
        from: useCaseName.get(dep.fromId) || '',
        to: useCaseName.get(dep.toId) || '',
      }))
      .filter((dep) => dep.from && dep.to && dep.from !== dep.to),
  }
  if (positions && Object.keys(positions).length) payload.positions = positions
  return payload
}

export function signatureOfUseCase(spec: UseCaseSpecDraft, positions?: Record<string, [number, number]>): string {
  const payload = toUseCaseJson(spec)
  return JSON.stringify(positions ? { ...payload, positions } : payload)
}

export interface UseCaseIssue {
  level: 'error' | 'warn'
  message: string
  targetId?: string
}

export function validateUseCaseSpec(spec: UseCaseSpecDraft): UseCaseIssue[] {
  const issues: UseCaseIssue[] = []
  const add = (level: UseCaseIssue['level'], message: string, targetId?: string) =>
    issues.push({ level, message, targetId })

  if (!spec.system.trim() && !spec.title.trim()) {
    add('warn', '建议填写系统边界名称或课题标题。')
  }
  if (charLength(spec.system.trim()) > USECASE_LIMITS.label) {
    add('error', `系统边界名超过 ${USECASE_LIMITS.label} 个字符。`)
  }
  if (charLength(spec.title.trim()) > USECASE_LIMITS.label) {
    add('error', `课题标题超过 ${USECASE_LIMITS.label} 个字符。`)
  }

  if (!spec.actors.length) add('error', '至少需要 1 个参与者。')
  if (spec.actors.length > USECASE_LIMITS.actors) {
    add('error', `参与者最多 ${USECASE_LIMITS.actors} 个，当前 ${spec.actors.length} 个。`)
  }
  if (!spec.useCases.length) add('error', '至少需要 1 个用例。')
  if (spec.useCases.length > USECASE_LIMITS.useCases) {
    add('error', `用例最多 ${USECASE_LIMITS.useCases} 个，当前 ${spec.useCases.length} 个。`)
  }
  if (spec.links.length > USECASE_LIMITS.links) {
    add('error', `关联最多 ${USECASE_LIMITS.links} 条，当前 ${spec.links.length} 条。`)
  }
  if (spec.dependencies.length > USECASE_LIMITS.dependencies) {
    add('error', `依赖最多 ${USECASE_LIMITS.dependencies} 条，当前 ${spec.dependencies.length} 条。`)
  }

  const actorNames = new Set<string>()
  for (const actor of spec.actors) {
    const name = actor.name.trim()
    const owner = name ? `「${name}」` : '（未命名参与者）'
    if (!name) add('error', '存在未命名的参与者。', actor.id)
    else {
      if (charLength(name) > USECASE_LIMITS.label) {
        add('error', `参与者名${owner}超过 ${USECASE_LIMITS.label} 个字符。`, actor.id)
      }
      if (actorNames.has(name)) add('error', `参与者名重复：${owner}。`, actor.id)
      actorNames.add(name)
    }
  }

  const useCaseNames = new Set<string>()
  for (const useCase of spec.useCases) {
    const name = useCase.name.trim()
    const owner = name ? `「${name}」` : '（未命名用例）'
    if (!name) add('error', '存在未命名的用例。', useCase.id)
    else {
      if (charLength(name) > USECASE_LIMITS.label) {
        add('error', `用例名${owner}超过 ${USECASE_LIMITS.label} 个字符。`, useCase.id)
      }
      if (useCaseNames.has(name)) add('error', `用例名重复：${owner}。`, useCase.id)
      if (actorNames.has(name)) add('error', `用例名${owner}与参与者重名。`, useCase.id)
      useCaseNames.add(name)
    }
  }

  const linkKeys = new Set<string>()
  const linkedActors = new Set<string>()
  const linkedUseCases = new Set<string>()
  for (const link of spec.links) {
    if (!link.actorId || !spec.actors.some((actor) => actor.id === link.actorId)) {
      add('error', '有关联未选择有效的参与者。', link.id)
      continue
    }
    if (!link.useCaseId || !spec.useCases.some((item) => item.id === link.useCaseId)) {
      add('error', '有关联未选择有效的用例。', link.id)
      continue
    }
    const key = `${link.actorId}::${link.useCaseId}`
    if (linkKeys.has(key)) add('error', '存在重复的参与者—用例关联。', link.id)
    linkKeys.add(key)
    linkedActors.add(link.actorId)
    linkedUseCases.add(link.useCaseId)
  }

  const depKeys = new Set<string>()
  const depTouched = new Set<string>()
  for (const dep of spec.dependencies) {
    if (!dep.fromId || !spec.useCases.some((item) => item.id === dep.fromId)) {
      add('error', '有依赖未选择有效的起点用例。', dep.id)
      continue
    }
    if (!dep.toId || !spec.useCases.some((item) => item.id === dep.toId)) {
      add('error', '有依赖未选择有效的终点用例。', dep.id)
      continue
    }
    if (dep.fromId === dep.toId) {
      add('error', '依赖不能指向同一个用例。', dep.id)
      continue
    }
    if (!['include', 'extend', 'generalize'].includes(dep.kind)) {
      add('error', '依赖类型无效。', dep.id)
      continue
    }
    const key = `${dep.kind}::${dep.fromId}::${dep.toId}`
    if (depKeys.has(key)) add('error', '存在重复的用例依赖。', dep.id)
    depKeys.add(key)
    depTouched.add(dep.fromId)
    depTouched.add(dep.toId)
  }

  if (spec.actors.length && spec.useCases.length && !spec.links.length) {
    add('warn', '还没有关联线：请把参与者连到用例。')
  }
  for (const actor of spec.actors) {
    if (actor.name.trim() && !linkedActors.has(actor.id)) {
      add('warn', `参与者「${actor.name.trim()}」尚未连接到任何用例。`, actor.id)
    }
  }
  for (const useCase of spec.useCases) {
    if (useCase.name.trim() && !linkedUseCases.has(useCase.id) && !depTouched.has(useCase.id)) {
      add('warn', `用例「${useCase.name.trim()}」尚未被任何参与者使用，也未出现在依赖中。`, useCase.id)
    }
  }

  return issues
}

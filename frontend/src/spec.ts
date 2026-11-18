import type {
  AttrDraft,
  Cardinality,
  DiagramPositions,
  EntityDraft,
  JsonSpec,
  RelationPositions,
  RelationDraft,
  SpecDraft,
} from './types'

/** 与后端 api.py / er_generator.py 的限制保持一致，便于在本地提前拦下会被 422 拒绝的规格 */
export const LIMITS = {
  entities: 24,
  relations: 40,
  attrs: 12,
  label: 24,
  coordinate: 48,
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

const CARDINALITIES = new Set<string>(['1', 'm', 'n', 'p'])

/** `m`、`M`、`*`、`∞` 都按多处理，与后端 _split_card 的宽松规则对齐 */
function normalizeCard(token: unknown): Cardinality | null {
  const raw = toText(token).toLowerCase().replace(/[*∞]/g, 'n')
  return CARDINALITIES.has(raw) ? (raw as Cardinality) : null
}

/** 解析属性数组：既支持 "*学号" 字符串，也支持 { name, pk } 对象 */
function parseAttributes(input: unknown, owner: string, notices: string[], allowPk: boolean): AttrDraft[] {
  if (input === undefined || input === null) return []
  if (!Array.isArray(input)) {
    notices.push(`「${owner}」的 attrs 不是数组，已忽略。`)
    return []
  }
  const attrs: AttrDraft[] = []
  const seen = new Set<string>()
  let duplicated = 0
  for (const item of input) {
    let name = ''
    let pk = false
    if (isObject(item)) {
      name = toText(item.name)
      pk = Boolean(item.pk)
    } else {
      const raw = toText(item)
      pk = raw.startsWith('*')
      name = raw.replace(/^\*+/, '').trim()
    }
    if (!name) continue
    if (seen.has(name)) {
      duplicated += 1
      continue
    }
    seen.add(name)
    attrs.push({ id: uid('attr'), name, pk: allowPk && pk })
  }
  if (duplicated) notices.push(`「${owner}」有 ${duplicated} 个重复属性名，已去重。`)
  return attrs
}

/** 解析基数：字符串 "1:n" 或数组 ["1","n"] 都接受；个数与端点数不一致时修复并提示 */
function parseCards(input: unknown, count: number, owner: string, notices: string[]): Cardinality[] {
  let tokens: unknown[]
  if (input === undefined || input === null || input === '') {
    tokens = count === 3 ? ['m', 'n', 'p'] : ['1', 'n']
  } else if (Array.isArray(input)) {
    tokens = input
  } else if (typeof input === 'string') {
    tokens = input.split(/[:：\-—,，/\s]+/).filter((part) => part !== '')
  } else {
    tokens = []
  }

  const cards: Cardinality[] = []
  const rejected: string[] = []
  for (const token of tokens) {
    const card = normalizeCard(token)
    if (card) {
      cards.push(card)
    } else {
      rejected.push(String(token))
      cards.push('n')
    }
  }
  if (rejected.length) {
    notices.push(`联系「${owner}」的基数「${rejected.join('、')}」无法识别，已按 n 处理。`)
  }
  if (cards.length !== count) {
    if (cards.length < count) {
      while (cards.length < count) cards.push('n')
    } else {
      cards.length = count
    }
    notices.push(`联系「${owner}」的基数个数与端点数不一致，已调整为 ${count} 个。`)
  }
  return cards
}

type ParseOutcome =
  | { ok: true; spec: SpecDraft; notices: string[]; positionsById?: DiagramPositions; relationPositionsById?: DiagramPositions }
  | { ok: false; error: string }

type NamedNode = { id: string; name: string }

export function parsePositions(input: unknown, nodes: readonly NamedNode[]): DiagramPositions | undefined {
  if (!isObject(input) || Object.keys(input).length !== nodes.length) return undefined
  const positions: DiagramPositions = {}
  for (const { id, name } of nodes) {
    if (!Object.prototype.hasOwnProperty.call(input, name)) return undefined
    const point = input[name]
    if (!Array.isArray(point) || point.length !== 2 || !point.every((coordinate) =>
      typeof coordinate === 'number' && Math.abs(coordinate) <= LIMITS.coordinate,
    )) return undefined
    positions[id] = [point[0], point[1]]
  }
  return positions
}

export function positionsByName(
  nodes: readonly NamedNode[],
  positionsById?: DiagramPositions,
): DiagramPositions | undefined {
  if (!positionsById || !nodes.length || Object.keys(positionsById).length !== nodes.length
      || nodes.some(({ id }) => !positionsById[id])) return undefined
  return Object.fromEntries(nodes.map(({ id, name }) => [name.trim(), positionsById[id]]))
}

/**
 * 把任意来源的规格 JSON 转成可编辑草稿。
 * - 属性支持 "*学号" 与 { name, pk }
 * - 联系端点支持 entities 数组，也支持 a / b / (c)
 * - 自联系（两端同一实体）、三元联系、联系属性都会保留
 * 结构性错误直接返回 error（调用方保留当前编辑内容），可修复的写法记入 notices。
 */
export function parseSpec(raw: unknown): ParseOutcome {
  if (!isObject(raw)) {
    return {
      ok: false,
      error: 'JSON 顶层必须是对象，形如 { "title": "…", "entities": [...], "relations": [...] }。',
    }
  }

  const notices: string[] = []
  const entitiesRaw = raw.entities
  if (!Array.isArray(entitiesRaw)) {
    return { ok: false, error: '缺少 entities 数组（规格至少要有一个实体）。' }
  }

  const entities: EntityDraft[] = []
  const nameSet = new Set<string>()
  for (let index = 0; index < entitiesRaw.length; index += 1) {
    const item = entitiesRaw[index]
    if (!isObject(item)) return { ok: false, error: `第 ${index + 1} 个实体不是对象，无法识别。` }
    const name = toText(item.name)
    if (!name) return { ok: false, error: `第 ${index + 1} 个实体缺少 name。` }
    if (nameSet.has(name)) return { ok: false, error: `实体名重复：「${name}」。` }
    nameSet.add(name)

    const attrs = parseAttributes(item.attrs, name, notices, true)
    if (!attrs.some((attr) => attr.pk)) {
      if (attrs.length) {
        attrs[0].pk = true
        notices.push(`「${name}」没有标记主键，已把「${attrs[0].name}」设为主键。`)
      } else {
        const keyName = charLength(name) + 2 <= LIMITS.label ? `${name}ID` : 'ID'
        attrs.push({ id: uid('attr'), name: keyName, pk: true })
        notices.push(`「${name}」没有任何属性，已补一个主键「${keyName}」。`)
      }
    }
    entities.push({ id: uid('entity'), name, attrs })
  }
  if (!entities.length) return { ok: false, error: 'entities 里没有任何实体。' }

  const idByName = new Map(entities.map((entity) => [entity.name, entity.id]))
  const relations: RelationDraft[] = []
  if (raw.relations !== undefined && raw.relations !== null && !Array.isArray(raw.relations)) {
    notices.push('relations 不是数组，已忽略。')
  }
  const relationsRaw = Array.isArray(raw.relations) ? raw.relations : []

  for (let index = 0; index < relationsRaw.length; index += 1) {
    const item = relationsRaw[index]
    if (!isObject(item)) return { ok: false, error: `第 ${index + 1} 条联系不是对象，无法识别。` }
    const name = toText(item.name) || '关联'
    if (!toText(item.name)) notices.push(`第 ${index + 1} 条联系没有名称，已命名为「关联」。`)

    let names: string[]
    if (Array.isArray(item.entities) && item.entities.length) {
      names = item.entities.map(toText)
    } else {
      names = [toText(item.a), toText(item.b)]
      if (toText(item.c)) names.push(toText(item.c))
    }
    // 保留空位以维持「端点顺序 ↔ 基数顺序」的对应关系，交给校验去提示补全
    if (names.length > 3) {
      notices.push(`联系「${name}」有 ${names.length} 个端点，当前只支持 2 或 3 个，已保留前 3 个。`)
      names = names.slice(0, 3)
    }

    const cards = parseCards(item.card, names.length, name, notices)
    const attrs = parseAttributes(item.attrs, `联系「${name}」`, notices, false)
    relations.push({
      id: uid('relation'),
      name,
      attrs,
      ends: names.map((entityName, endIndex) => {
        const entityId = idByName.get(entityName)
        return {
          entityId: entityId ?? '',
          card: cards[endIndex],
          missingName: entityId ? undefined : entityName || undefined,
        }
      }),
    })
  }

  const positionsById = parsePositions(raw.positions, entities)
  if (raw.positions !== undefined && !positionsById) {
    notices.push('布局坐标无效或与实体不匹配，出图时将自动排版。')
  }
  let relationPositionsById: DiagramPositions | undefined
  if (raw.relationPositions !== undefined) {
    const points = raw.relationPositions
    if (positionsById && Array.isArray(points) && points.length === relations.length
        && points.length === relationsRaw.length && points.every((point) => point === null ||
          Array.isArray(point) && point.length === 2 && point.every((value) =>
            typeof value === 'number' && Math.abs(value) <= LIMITS.coordinate))) {
      relationPositionsById = Object.fromEntries(relations.flatMap(({ id }, index) =>
        points[index] === null ? [] : [[id, points[index]]]))
    } else {
      notices.push('联系布局坐标无效，将自动摆放联系。')
    }
  }
  return { ok: true, spec: { title: toText(raw.title), entities, relations }, notices, positionsById, relationPositionsById }
}

/**
 * 草稿 → 提交给后端的规格 / 导出的 JSON。
 * 两者用同一份输出，保证「导出的 JSON 就是刚才出图的那份规格」。
 */
export function toJsonSpec(spec: SpecDraft, positions?: DiagramPositions, relationPositions?: RelationPositions): JsonSpec {
  const nameById = new Map(spec.entities.map((entity) => [entity.id, entity.name.trim()]))
  return {
    title: spec.title.trim(),
    entities: spec.entities.map((entity) => ({
      name: entity.name.trim(),
      attrs: entity.attrs
        .map((attr) => `${attr.pk ? '*' : ''}${attr.name.trim()}`)
        .filter((label) => label !== '' && label !== '*'),
    })),
    relations: spec.relations.map((relation) => ({
      name: relation.name.trim() || '关联',
      entities: relation.ends.map((end) => nameById.get(end.entityId) ?? ''),
      card: relation.ends.map((end) => end.card),
      attrs: relation.attrs.map((attr) => attr.name.trim()).filter((label) => label !== ''),
    })),
    ...(positions ? { positions } : {}),
    ...(positions && relationPositions?.some(Boolean) ? { relationPositions } : {}),
  }
}

/** 规格指纹：用于判断预览是否已经落后于编辑内容 */
export function signatureOf(spec: SpecDraft, positions?: DiagramPositions, relationPositions?: RelationPositions): string {
  return JSON.stringify(toJsonSpec(spec, positions, relationPositions))
}

export interface Issue {
  level: 'error' | 'warn'
  message: string
  targetId?: string
}

/** 出图前的本地校验，规则与后端 validate_web_spec 对齐（错误会阻止提交，警告只提示） */
export function validateSpec(spec: SpecDraft): Issue[] {
  const issues: Issue[] = []
  const add = (level: Issue['level'], message: string, targetId?: string) => issues.push({ level, message, targetId })

  if (!spec.entities.length) add('error', '至少需要 1 个实体。')
  if (spec.entities.length > LIMITS.entities) {
    add('error', `实体最多 ${LIMITS.entities} 个，当前 ${spec.entities.length} 个。`)
  }
  if (spec.relations.length > LIMITS.relations) {
    add('error', `联系最多 ${LIMITS.relations} 条，当前 ${spec.relations.length} 条。`)
  }

  const entityNames = new Set<string>()
  for (const entity of spec.entities) {
    const push = (level: Issue['level'], message: string) => add(level, message, entity.id)
    const name = entity.name.trim()
    const owner = name ? `「${name}」` : '（未命名实体）'
    if (!name) {
      push('error', '存在未命名的实体，请填写实体名。')
    } else {
      if (charLength(name) > LIMITS.label) {
        push('error', `实体名${owner}超过 ${LIMITS.label} 个字符。`)
      }
      if (entityNames.has(name)) push('error', `实体名重复：${owner}。`)
      entityNames.add(name)
    }
    if (entity.attrs.length > LIMITS.attrs) {
      push('error', `实体${owner}有 ${entity.attrs.length} 个属性，最多 ${LIMITS.attrs} 个（含主键）。`)
    }
    const attrNames = new Set<string>()
    for (const attr of entity.attrs) {
      const attrName = attr.name.trim()
      if (!attrName) {
        push('error', `实体${owner}有属性没写名字。`)
        continue
      }
      if (charLength(attrName) > LIMITS.label) {
        push('error', `实体${owner}的属性名「${attrName}」超过 ${LIMITS.label} 个字符。`)
      }
      if (attrName.startsWith('*')) {
        push('error', `属性名「${attrName}」不能以 * 开头，主键请用勾选框标记。`)
      }
      if (attrNames.has(attrName)) push('error', `实体${owner}的属性名「${attrName}」重复。`)
      attrNames.add(attrName)
    }
    if (!entity.attrs.some((attr) => attr.pk)) {
      if (entity.attrs.length === LIMITS.attrs) {
        push('error', `实体${owner}已有 ${LIMITS.attrs} 个属性。请勾选主键，或腾出一个属性位置让系统自动补主键。`)
      } else if (entity.attrs.length < LIMITS.attrs) {
        push('warn', `实体${owner}没有主键，后端会自动补一个。`)
      }
    }
  }

  const connectedEntities = new Set<string>()
  for (const relation of spec.relations) {
    const push = (level: Issue['level'], message: string) => add(level, message, relation.id)
    const name = relation.name.trim()
    const owner = name ? `「${name}」` : '（未命名联系）'
    if (!name) push('warn', '有联系没写名称，将按「关联」出图。')
    else if (charLength(name) > LIMITS.label) push('error', `联系名${owner}超过 ${LIMITS.label} 个字符。`)

    if (relation.ends.length < 2) push('error', `联系${owner}至少需要 2 个端点。`)
    if (relation.ends.length > 3) push('error', `联系${owner}最多 3 个端点。`)

    relation.ends.forEach((end, index) => {
      if (!end.entityId) {
        const hint = end.missingName ? `（原文件里的「${end.missingName}」不在实体列表中）` : ''
        push('error', `联系${owner}的第 ${index + 1} 个端点还没选实体${hint}。`)
      } else if (!spec.entities.some((entity) => entity.id === end.entityId)) {
        push('error', `联系${owner}的第 ${index + 1} 个端点引用了已删除的实体，请重新选择。`)
      }
    })

    const distinct = new Set(relation.ends.map((end) => end.entityId))
    if (distinct.size > 1 && relation.ends.length >= 2 && relation.ends.length <= 3
        && relation.ends.every((end) => end.entityId)) {
      relation.ends.forEach((end) => {
        if (end.entityId) connectedEntities.add(end.entityId)
      })
    }

    if (relation.ends.length === 3 && relation.ends.every((end) => end.entityId)) {
      if (distinct.size < 3) push('error', `三元联系${owner}的三个端点必须是不同的实体。`)
    }

    if (relation.attrs.length > LIMITS.attrs) {
      push('error', `联系${owner}有 ${relation.attrs.length} 个联系属性，最多 ${LIMITS.attrs} 个。`)
    }
    const attrNames = new Set<string>()
    for (const attr of relation.attrs) {
      const attrName = attr.name.trim()
      if (!attrName) {
        push('error', `联系${owner}有联系属性没写名字。`)
        continue
      }
      if (charLength(attrName) > LIMITS.label) {
        push('error', `联系${owner}的属性名「${attrName}」超过 ${LIMITS.label} 个字符。`)
      }
      if (attrNames.has(attrName)) push('error', `联系${owner}的属性名「${attrName}」重复。`)
      attrNames.add(attrName)
    }
  }

  if (spec.entities.length > 1) {
    const isolated = spec.entities.filter((entity) => entity.name.trim() && !connectedEntities.has(entity.id))
    for (const entity of isolated) {
      add('warn', `「${entity.name.trim()}」未连接其他实体，会在整体图中单独显示。请核对是否需要添加联系。`, entity.id)
    }
  }

  return issues
}

/** 新建实体 / 联系时用，保证名字初始不重复 */
export function uniqueName(base: string, taken: string[]): string {
  if (!taken.includes(base)) return base
  let index = 2
  while (taken.includes(`${base}${index}`)) index += 1
  return `${base}${index}`
}

export const newAttr = (name = '', pk = false): AttrDraft => ({ id: uid('attr'), name, pk })

export const newEntity = (name: string): EntityDraft => ({
  id: uid('entity'),
  name,
  attrs: [newAttr('编号', true)],
})

export function newRelation(spec: SpecDraft): RelationDraft {
  const [first, second] = spec.entities
  return {
    id: uid('relation'),
    name: uniqueName('联系', spec.relations.map((relation) => relation.name)),
    attrs: [],
    ends: [
      { entityId: first?.id ?? '', card: '1' },
      { entityId: second?.id ?? '', card: 'n' },
    ],
  }
}

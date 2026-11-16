import courseSelection from '../../examples/course-selection.json'

/**
 * 「载入选课样例」使用仓库里 examples/course-selection.json 的原始内容，
 * 走和导入完全相同的解析路径，保证样例与后端/仓库文件始终一致。
 */
export const SAMPLE_JSON: unknown = courseSelection
export const SAMPLE_NAME: string = 'examples/course-selection.json'

/**
 * 示例规格的规模统计。从样例文件算出来而不是写死，
 * 样例改了数字跟着变，欢迎页不会说假话。
 */
export function sampleStats(json: unknown = SAMPLE_JSON) {
  const spec = json as {
    entities?: { attrs?: string[] }[]
    relations?: { attrs?: string[] }[]
  }
  const entities = spec.entities ?? []
  const relations = spec.relations ?? []
  const items = [...entities, ...relations]
  return {
    entities: entities.length,
    relations: relations.length,
    attrs: items.reduce((sum, item) => sum + (item.attrs?.length ?? 0), 0),
    keys: entities.reduce(
      (sum, entity) => sum + (entity.attrs ?? []).filter((attr) => attr.startsWith('*')).length,
      0,
    ),
  }
}

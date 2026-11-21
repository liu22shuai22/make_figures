/** 实体、联系、属性的可编辑草稿模型。id 只在前端内部使用，提交给后端时统一换成名称。 */

/** 工作台图种：E-R 与 UML 用例图共用一页，靠顶栏切换 */
export type DiagramKind = 'er' | 'usecase'

export type ActorKind = 'primary' | 'secondary'

export interface ActorDraft {
  id: string
  name: string
  kind: ActorKind
}

export interface UseCaseDraft {
  id: string
  name: string
}

/** 参与者与用例之间的关联（通信）线 */
export interface UseCaseLinkDraft {
  id: string
  actorId: string
  useCaseId: string
}

/** 用例之间的依赖：include / extend / 泛化 */
export type UseCaseDepKind = 'include' | 'extend' | 'generalize'

export interface UseCaseDepDraft {
  id: string
  kind: UseCaseDepKind
  /** 箭头起点用例（include/extend 的源；泛化的子用例） */
  fromId: string
  /** 箭头终点用例（include/extend 的目标；泛化的父用例） */
  toId: string
}

export interface UseCaseSpecDraft {
  title: string
  /** 系统边界名称，画在用例外围方框上 */
  system: string
  actors: ActorDraft[]
  useCases: UseCaseDraft[]
  links: UseCaseLinkDraft[]
  dependencies: UseCaseDepDraft[]
}

/** 提交 / 导出用的用例图 JSON（无内部 id） */
export interface UseCaseJsonSpec {
  kind: 'usecase'
  title: string
  system: string
  actors: { name: string; kind: ActorKind }[]
  useCases: { name: string }[]
  links: { actor: string; useCase: string }[]
  dependencies: { kind: UseCaseDepKind; from: string; to: string }[]
  positions?: DiagramPositions
  dependencyLabelPositions?: RelationPositions
}

export type Cardinality = '1' | 'm' | 'n' | 'p'

export const CARDINALITIES: { value: Cardinality; label: string }[] = [
  { value: '1', label: '1（一）' },
  { value: 'm', label: 'm（多）' },
  { value: 'n', label: 'n（多）' },
  { value: 'p', label: 'p（多）' },
]

export interface AttrDraft {
  id: string
  name: string
  /** 主键，出图时名称加下划线 */
  pk: boolean
}

export interface EntityDraft {
  id: string
  name: string
  attrs: AttrDraft[]
}

export interface EndDraft {
  /** 指向 EntityDraft.id；空字符串表示尚未选择 */
  entityId: string
  card: Cardinality
  /** 导入时原文件里写了、但当前实体列表里不存在的实体名（用于提示，不会提交） */
  missingName?: string
}

export interface RelationDraft {
  id: string
  name: string
  /** 2 或 3 个端点，顺序即图片里基数标注的顺序 */
  ends: EndDraft[]
  attrs: AttrDraft[]
}

export interface SpecDraft {
  title: string
  entities: EntityDraft[]
  relations: RelationDraft[]
}

export type ImageFormat = 'png' | 'svg'

export interface RenderStyle {
  font: 'simsun' | 'simhei' | 'msyh' | 'simkai' | 'simfang'
  fontSize: number
  lineWidth: number
}

export const DEFAULT_RENDER_STYLE: RenderStyle = { font: 'simsun', fontSize: 10.5, lineWidth: 0.5 }
export const CANVAS_RATIOS = ['auto', '16:9', '4:3', '1:1', '9:16'] as const
export type CanvasRatio = (typeof CANVAS_RATIOS)[number]

export type DiagramPositions = Record<string, [number, number]>
export type RelationPositions = ([number, number] | null)[]

/** 提交给 /api/render 的规格，同时也就是「导出 JSON」的内容 */
export interface JsonSpec {
  title: string
  entities: { name: string; attrs: string[] }[]
  relations: { name: string; entities: string[]; card: Cardinality[]; attrs: string[] }[]
  positions?: DiagramPositions
  relationPositions?: RelationPositions
}

export interface RenderedImage {
  filename: string
  /** 图片 data URL，可直接放进 <img src> */
  url: string
}

export interface RenderedEntityImage extends RenderedImage {
  entity: string
  frame?: ImageFrame
}

export interface EntityBox {
  entity: string
  x: number
  y: number
  width: number
  height: number
}

export interface DiagramFrame {
  x: number
  y: number
  width: number
  height: number
}

export interface ImageFrame extends DiagramFrame {
  contentFrame?: DiagramFrame
}

export interface DiagramLayout extends ImageFrame {
  entities: EntityBox[]
  relations?: (Omit<EntityBox, 'entity'> & { index: number; name: string })[]
  dependencyLabels?: DiagramLayout['relations']
  referenceCount?: number
  useCaseQuality?: {
    overlaps: number
    boxHits: number
    lineConflicts: number
    labelConflicts: number
  }
  quality?: {
    planar: boolean
    overlaps: number
    boxHits: number
    lineConflicts: number
    labelConflicts: number
  }
}

/** 欢迎页跳到工作台时携带的一次性指令 */
export interface WorkbenchCommand {
  type: 'focus' | 'sample' | 'usecase-sample'
  nonce: number
}

export interface RenderResult {
  style?: RenderStyle
  format: ImageFormat
  ratio: CanvasRatio
  /** 生成这张图时使用的规格指纹，用来判断「有修改，待重新排版」 */
  signature: string
  renderedAt: number
  overview: RenderedImage
  entities: RenderedEntityImage[]
  layout?: DiagramLayout
}

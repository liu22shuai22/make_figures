/** 实体、联系、属性的可编辑草稿模型。id 只在前端内部使用，提交给后端时统一换成名称。 */

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
export const CANVAS_RATIOS = ['auto', '16:9', '4:3', '1:1', '9:16'] as const
export type CanvasRatio = (typeof CANVAS_RATIOS)[number]

export type DiagramPositions = Record<string, [number, number]>

/** 提交给 /api/render 的规格，同时也就是「导出 JSON」的内容 */
export interface JsonSpec {
  title: string
  entities: { name: string; attrs: string[] }[]
  relations: { name: string; entities: string[]; card: Cardinality[]; attrs: string[] }[]
  positions?: DiagramPositions
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
  referenceCount?: number
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
  type: 'focus' | 'sample'
  nonce: number
}

export interface RenderResult {
  format: ImageFormat
  ratio: CanvasRatio
  /** 生成这张图时使用的规格指纹，用来判断「有修改，待重新排版」 */
  signature: string
  renderedAt: number
  overview: RenderedImage
  entities: RenderedEntityImage[]
  layout?: DiagramLayout
}

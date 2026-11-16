import type { CanvasRatio, DiagramFrame, ImageFormat, ImageFrame, RenderResult } from './types'

export async function reframeDiagrams(source: RenderResult, ratio: CanvasRatio): Promise<RenderResult> {
  if (ratio === source.ratio) return source
  if (!source.layout) throw new Error('当前图缺少画布数据，请先重新排版。')
  const fromAuto = source.ratio === 'auto'
  const overview = await reframeImage(source.overview.url, source.format, source.layout, ratio, fromAuto)
  const entities: RenderResult['entities'] = []
  for (const image of source.entities) {
    const adjusted = await reframeImage(image.url, source.format, image.frame, ratio, fromAuto)
    entities.push({ ...image, url: adjusted.url, frame: adjusted.frame })
  }
  return { ...source, ratio, entities, overview: { ...source.overview, url: overview.url },
    layout: { ...source.layout, ...overview.frame } }
}

async function reframeImage(url: string, format: ImageFormat, layout: ImageFrame | undefined,
  ratio: CanvasRatio, fromAuto: boolean) {
  const content = layout?.contentFrame ?? (fromAuto ? layout : undefined)
  if (!layout || !content) throw new Error('当前图缺少画布数据，请先重新排版。')
  const [columns, rows] = ratio === 'auto' ? [content.width, content.height] : ratio.split(':').map(Number)
  const unit = Math.max(content.width / columns, content.height / rows)
  const width = unit * columns
  const height = unit * rows
  const frame: DiagramFrame = {
    x: content.x - (width - content.width) / 2,
    y: content.y - (height - content.height) / 2,
    width,
    height,
  }
  const adjustedUrl = format === 'svg'
    ? await reframeSvg(url, layout, frame)
    : await reframePng(url, layout, frame, ratio)
  return { url: adjustedUrl, frame: { ...frame, contentFrame: content } }
}

async function reframeSvg(url: string, source: DiagramFrame, target: DiagramFrame) {
  const xml = await (await fetch(url)).text()
  const svg = new DOMParser().parseFromString(xml, 'image/svg+xml').documentElement
  const [left, top, width, height] = (svg.getAttribute('viewBox') ?? '').trim().split(/\s+/).map(Number)
  if (svg.localName !== 'svg' || !(width > 0 && height > 0)) throw new Error('无法读取 SVG 画布。')
  const sx = width / source.width
  const sy = height / source.height
  const viewX = left + (target.x - source.x) * sx
  const viewY = top + (target.y - source.y) * sy
  const viewWidth = target.width * sx
  const viewHeight = target.height * sy
  svg.setAttribute('viewBox', `${viewX} ${viewY} ${viewWidth} ${viewHeight}`)
  svg.setAttribute('width', `${viewWidth}pt`)
  svg.setAttribute('height', `${viewHeight}pt`)
  const background = svg.ownerDocument.createElementNS(svg.namespaceURI, 'rect')
  background.setAttribute('x', String(viewX))
  background.setAttribute('y', String(viewY))
  background.setAttribute('width', String(viewWidth))
  background.setAttribute('height', String(viewHeight))
  background.setAttribute('fill', 'white')
  svg.prepend(background)
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(svg))
}

async function reframePng(url: string, source: DiagramFrame, target: DiagramFrame, ratio: CanvasRatio) {
  const image = new Image()
  image.src = url
  await image.decode()
  const scale = Math.min(image.naturalWidth / source.width, image.naturalHeight / source.height,
    Math.sqrt(24_000_000 / (target.width * target.height)), 12_000 / Math.max(target.width, target.height))
  const canvas = document.createElement('canvas')
  if (ratio === 'auto') {
    canvas.width = Math.max(1, Math.round(target.width * scale))
    canvas.height = Math.max(1, Math.round(target.height * scale))
  } else {
    const [columns, rows] = ratio.split(':').map(Number)
    const pixels = Math.max(1, Math.floor(target.width * scale / columns))
    canvas.width = pixels * columns
    canvas.height = pixels * rows
  }
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法创建 PNG 画布。')
  const sx = canvas.width / target.width
  const sy = canvas.height / target.height
  ctx.fillStyle = 'white'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(image, (source.x - target.x) * sx, (source.y - target.y) * sy, source.width * sx, source.height * sy)
  return canvas.toDataURL('image/png')
}

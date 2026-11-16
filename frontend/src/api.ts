import type { CanvasRatio, DiagramLayout, ImageFormat, JsonSpec, RenderedEntityImage, RenderedImage } from './types'

type ApiErrorKind = 'network' | 'timeout' | 'http' | 'shape'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number

  constructor(message: string, kind: ApiErrorKind, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

/** 后端出图上限为 55 秒，前端留出传输和解析图片的时间。 */
const RENDER_TIMEOUT_MS = 90_000
/** 后端模型调用和重试共用 120 秒预算，浏览器留出处理响应的时间。 */
const GENERATE_TIMEOUT_MS = 135_000

const NETWORK_HINT =
  '连不上后端服务。请确认已在 D:\\make_figures 下运行 python -m uvicorn api:app，并且 http://127.0.0.1:8000/docs 能打开。'

interface RawResponse {
  status: number
  data: unknown
  rawBody: string
}

interface ReviewFinding {
  kind: 'entity' | 'relation' | 'model'
  index: number | null
  message: string
}

export interface ModelReview {
  structural: ReviewFinding[]
  status: 'local'
}

export async function reviewSpec(spec: JsonSpec, token: string): Promise<ModelReview> {
  const result = await postJson('/api/assistant/review', { spec }, {
    token, timeoutMs: 60_000, timeoutMessage: '结构检查超时，请稍后重试。',
  })
  if (!isOk(result.status)) {
    const hint = result.status === 401 ? '请重新登录后再运行 AI 审查。' :
      detailToText(detailOf(result.data)) || '暂时无法进行 AI 审查，请稍后重试。'
    throw new ApiError(hint, 'http', result.status)
  }
  const body = result.data as ModelReview | null
  if (!body || !Array.isArray(body.structural) || body.status !== 'local') {
    throw new ApiError('助手未返回有效的审查结果。', 'shape')
  }
  return body
}

/** 统一的 POST JSON：只处理网络层与解析层，状态码语义交给调用方 */
async function postJson(
  path: string,
  payload: unknown,
  options: { timeoutMs: number; timeoutMessage: string; token: string },
): Promise<RawResponse> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), options.timeoutMs)
  try {
    let response: Response
    try {
      response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${options.token}` },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
    } catch (error) {
      if ((error as Error)?.name === 'AbortError') throw new ApiError(options.timeoutMessage, 'timeout')
      throw new ApiError(NETWORK_HINT, 'network')
    }

    const rawBody = await response.text()
    let data: unknown = null
    if (rawBody.trim()) {
      try {
        data = JSON.parse(rawBody)
      } catch {
        data = null
      }
    }
    return { status: response.status, data, rawBody }
  } finally {
    window.clearTimeout(timer)
  }
}

const isOk = (status: number) => status >= 200 && status < 300

/** FastAPI 的 detail 可能是字符串，也可能是校验错误数组 */
function detailToText(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          const entry = item as { loc?: unknown; msg?: unknown }
          const loc = Array.isArray(entry.loc)
            ? entry.loc.map(String).filter((part) => part !== 'body' && part !== 'query').join('.')
            : ''
          const msg = typeof entry.msg === 'string' ? entry.msg : ''
          return [loc, msg].filter(Boolean).join('：')
        }
        return ''
      })
      .filter(Boolean)
    return parts.length ? parts.join('；') : null
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return null
}

function detailOf(data: unknown): unknown {
  return data && typeof data === 'object' ? (data as { detail?: unknown }).detail : undefined
}

/** Vite 代理在后端未启动时会返回 500/502 且响应体是 HTML */
const looksLikeHtml = (rawBody: string) => !rawBody.trim().startsWith('{')

/* ------------------------------ 出图 ------------------------------ */

function messageForRenderFailure(status: number, detail: unknown, rawBody: string): string {
  const detailText = detailToText(detail)
  switch (status) {
    case 401:
      return detailText || '请先登录，再生成或排版 E-R 图。'
    case 413:
      return '规格太大（超过 64 KB），请减少实体、属性或联系后再试。'
    case 422:
      if (detailText?.includes('零交叉')) return detailText
      return detailText
        ? `规格没通过后端校验：${detailText}。按提示修改左侧内容后重试。`
        : '规格没通过后端校验（422），请检查实体、属性、联系的字段。'
    case 503:
      return '后端正在为另一份规格出图，请等几秒再点「重新排版」。'
    case 504:
      return '排版超时，请减少实体或联系的数量后重试。'
    default:
      break
  }
  if (looksLikeHtml(rawBody)) {
    return `后端服务不可用（HTTP ${status}）。请确认已在 127.0.0.1:8000 运行 python -m uvicorn api:app。`
  }
  if (status >= 500) {
    return detailText
      ? `出图失败（HTTP ${status}）：${detailText}。请检查后端的中文字体和运行日志。`
      : `后端出图进程出错（HTTP ${status}），请检查后端运行日志里的报错信息。`
  }
  return `请求失败（HTTP ${status}）${detailText ? `：${detailText}` : ''}。`
}

interface RenderResponse {
  overview: RenderedImage
  entities: RenderedEntityImage[]
  layout?: DiagramLayout
}

/**
 * POST /api/render，查询参数指定图片格式和整体图画布比例。
 * 请求体直接是规格对象；响应里 overview/entities 的 url 都是 data URL。
 */
export async function renderSpec(payload: JsonSpec, format: ImageFormat, ratio: CanvasRatio, token: string): Promise<RenderResponse> {
  const query = new URLSearchParams({ format, aspect: ratio })
  const result = await postJson(`/api/render?${query}`, payload, {
    token,
    timeoutMs: RENDER_TIMEOUT_MS,
    timeoutMessage: '请求超时（90 秒），后端可能正忙，请稍后重试。',
  })

  if (!isOk(result.status)) {
    throw new ApiError(
      messageForRenderFailure(result.status, detailOf(result.data), result.rawBody),
      'http',
      result.status,
    )
  }

  const body = result.data as Partial<RenderResponse> | null
  if (!body || typeof body !== 'object' || !body.overview?.url) {
    throw new ApiError('后端返回的数据不完整（缺少 overview）。请检查后端版本。', 'shape')
  }

  return {
    overview: { filename: body.overview.filename, url: body.overview.url },
    layout: body.layout,
    entities: Array.isArray(body.entities)
      ? body.entities
          .filter((item) => item && item.url)
          .map((item) => ({ entity: item.entity, filename: item.filename, url: item.url, frame: item.frame }))
      : [],
  }
}

/* --------------------------- 自然语言生成 --------------------------- */

function messageForGenerateFailure(status: number, detail: unknown, rawBody: string): string {
  const detailText = detailToText(detail)
  switch (status) {
    case 401:
      return detailText || '请先登录，再生成或排版 E-R 图。'
    case 404:
      return '后端还没有 /api/generate 接口（HTTP 404）。请更新 api.py 并重启 uvicorn 后再试。'
    case 413:
      return '描述太长，请精简后再试。'
    case 422:
      return detailText
        ? `描述没通过后端校验：${detailText}。请写 1–4000 字的系统描述后再试。`
        : '描述没通过后端校验（422），请写 1–4000 字的系统描述后再试。'
    case 502:
      if (detailText?.startsWith('模型规格未通过校验')) return detailText
      if (detailText?.startsWith('硅基流动主入口和备用入口均未成功')) return detailText
      if (detailText?.includes('HTTP 401')) {
        return '模型服务拒绝了 API Key（401）。请在后端终端重新输入当前服务商的 API Key，再试一次。'
      }
      if (detailText?.includes('RemoteDisconnected')) {
        return '模型服务的连接提前断开，请稍后用原描述重试。'
      }
      return detailText ? `生成失败（502）：${detailText}` : '模型服务请求失败（502），请稍后重试。'
    case 503:
      return detailText
        ? `暂时无法生成（503）：${detailText}。`
        : '模型未配置或正忙（503），请确认后端已配置模型 API Key，或稍后重试。'
    case 504:
      return detailText ? `生成超时（504）：${detailText}` : '等待模型响应超时（504），请稍后重试。'
    default:
      break
  }
  if (looksLikeHtml(rawBody)) {
    return `后端服务不可用（HTTP ${status}）。请确认已在 127.0.0.1:8000 运行 python -m uvicorn api:app。`
  }
  if (status >= 500) {
    return detailText ? `生成失败（HTTP ${status}）：${detailText}` : `生成失败（HTTP ${status}），请查看后端日志。`
  }
  return `生成失败（HTTP ${status}）${detailText ? `：${detailText}` : ''}。`
}

/**
 * POST /api/generate  { "text": "..." }
 * 成功返回 { "spec": {...} }，这里只取出 spec，交给 parseSpec 解析。
 */
export async function generateSpec(text: string, token: string): Promise<unknown> {
  const result = await postJson(
    '/api/generate',
    { text },
    {
      token,
      timeoutMs: GENERATE_TIMEOUT_MS,
      timeoutMessage: '等待模型响应超过 135 秒，请稍后重试。',
    },
  )

  if (!isOk(result.status)) {
    throw new ApiError(
      messageForGenerateFailure(result.status, detailOf(result.data), result.rawBody),
      'http',
      result.status,
    )
  }

  const spec = result.data && typeof result.data === 'object' ? (result.data as { spec?: unknown }).spec : undefined
  if (!spec || typeof spec !== 'object') {
    throw new ApiError('后端返回的数据里没有 spec。请检查后端版本。', 'shape')
  }
  return spec
}

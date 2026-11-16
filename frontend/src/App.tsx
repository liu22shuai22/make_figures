import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import EntityCard from './components/EntityCard'
import RelationCard from './components/RelationCard'
import SpecSearch from './components/SpecSearch'
import PreviewPanel from './components/PreviewPanel'
import DescribeBox, { DESCRIBE_LIMIT } from './components/DescribeBox'
import type { AssistantDraft } from './components/ModelAssistant'
import { reframeDiagrams } from './canvasRatio'
import BrandMark from './components/BrandMark'
import ProviderIcon from './components/ProviderIcon'
import { ApiError, generateSpec, renderSpec } from './api'
import { fetchProviders, type ProviderPublic } from './providersApi'
import { downloadDataUrl, downloadText, safeFileName } from './download'
import { SAMPLE_JSON } from './sample'
import {
  LIMITS,
  newEntity,
  newRelation,
  parseSpec,
  signatureOf,
  toJsonSpec,
  uniqueName,
  validateSpec,
} from './spec'
import type {
  CanvasRatio,
  DiagramPositions,
  EntityDraft,
  ImageFormat,
  RelationDraft,
  RenderResult,
  SpecDraft,
  WorkbenchCommand,
} from './types'

interface Notice {
  title: string
  items: string[]
  /** 提示条上的快捷入口，例如生成成功后的「查看生成结果」 */
  action?: { label: string; run: () => void }
}

/** 工作台顶部失败条：按类型决定是否露出渠道/登录入口 */
interface WorkbenchError {
  title: string
  detail: string
  action?: 'channel' | 'login'
  /** 右侧仍保留上一次成功预览 */
  keptPreview?: boolean
}

const EMPTY_SPEC: SpecDraft = { title: '', entities: [], relations: [] }

function readSample(): { spec: SpecDraft; notices: string[] } {
  const parsed = parseSpec(SAMPLE_JSON)
  if (parsed.ok) return { spec: parsed.spec, notices: parsed.notices }
  return { spec: EMPTY_SPEC, notices: [] }
}

interface AppProps {
  /** 欢迎页传来的一次性指令：聚焦描述框，或载入选课样例 */
  command?: WorkbenchCommand | null
  onHome: () => void
  onUsage: () => void
  onLogin: () => void
  /** 当前登录用户名；null 表示未登录。工作台不展示用户名，只在未登录时给出登录入口 */
  username: string | null
  token?: string
  onOpenApiPlatform: () => void
  onAssistantDraft: (draft: AssistantDraft) => void
}

export default function App({ command, onHome, onUsage, onLogin, username, token, onOpenApiPlatform, onAssistantDraft }: AppProps) {
  const [spec, setSpec] = useState<SpecDraft>(EMPTY_SPEC)
  const [positionsById, setPositionsById] = useState<DiagramPositions>()
  const [format, setFormat] = useState<ImageFormat>('png')
  const [ratio, setRatio] = useState<CanvasRatio>('auto')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<RenderResult | null>(null)
  const [error, setError] = useState<WorkbenchError | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [tab, setTab] = useState('overview')
  const [locatedId, setLocatedId] = useState<string>()

  /** 自然语言生成 */
  const [describe, setDescribe] = useState('')
  const [describeError, setDescribeError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [activeChannel, setActiveChannel] = useState<ProviderPublic | null>(null)
  /** 空草稿时默认收起手动编辑区，避免冷启动被实体/联系空壳占满 */
  const [manualOpen, setManualOpen] = useState(false)

  const fileInput = useRef<HTMLInputElement>(null)

  const refreshActiveChannel = useCallback(async () => {
    if (!token) {
      setActiveChannel(null)
      return
    }
    try {
      const payload = await fetchProviders(token)
      const active =
        payload.providers.find((item) => item.id === payload.active_id) || payload.providers[0] || null
      setActiveChannel(active)
    } catch {
      /* 工作台不因渠道读取失败打断主流程 */
    }
  }, [token])

  useEffect(() => {
    void refreshActiveChannel()
  }, [refreshActiveChannel])

  useEffect(() => {
    const onFocus = () => void refreshActiveChannel()
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refreshActiveChannel()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refreshActiveChannel])
  // 状态更新是异步的，用 ref 同步拦住连点导致的重复提交
  const submitting = useRef(false)
  const generatingRef = useRef(false)
  const originalResult = useRef<RenderResult | null>(null)
  const currentSpec = useRef(spec)
  const lastGeneratedSpec = useRef<SpecDraft | null>(null)
  const descriptionVersion = useRef(0)
  useLayoutEffect(() => { currentSpec.current = spec }, [spec])

  const locateSpec = useCallback((id: string) => {
    const target = document.getElementById(`spec-${id}`)
    if (!target) return
    setLocatedId(id)
    target.focus({ preventScroll: true })
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    target.scrollIntoView({ behavior: reduceMotion ? 'instant' : 'smooth', block: 'center', inline: 'nearest' })
  }, [])

  const emptyDraft = !spec.title.trim() && !spec.entities.length && !spec.relations.length
  const issues = useMemo(() => emptyDraft ? [] : validateSpec(spec), [spec, emptyDraft])
  useLayoutEffect(() => {
    onAssistantDraft({ spec, issues, onLocate: locateSpec })
  }, [spec, issues, locateSpec, onAssistantDraft])
  const errors = useMemo(() => issues.filter((issue) => issue.level === 'error'), [issues])
  const warnings = useMemo(() => issues.filter((issue) => issue.level === 'warn'), [issues])
  const blocked = !spec.entities.length || errors.length > 0

  const savedPositions = useMemo<DiagramPositions | undefined>(() => {
    const entities = spec.entities
    if (!positionsById || Object.keys(positionsById).length !== entities.length
        || entities.some(({ id }) => !positionsById[id])) return undefined
    return Object.fromEntries(entities.map(({ name, id }) => [name.trim(), positionsById[id]]))
  }, [spec.entities, positionsById])
  const draftSignature = useMemo(() => signatureOf(spec, savedPositions), [spec, savedPositions])
  const sameDraft = result !== null && result.signature === `${draftSignature}|${result.format}`
  const ratioPending = result !== null && result.ratio !== ratio
  const stale = result !== null && (!sameDraft || result.format !== format || ratioPending)
  const formatOnly = sameDraft && !!savedPositions && !ratioPending && result.format !== format
  const ratioOnly = sameDraft && ratioPending && result.format === format
  const renderLabel = ratioOnly ? '应用比例' : formatOnly ? '更新格式' : savedPositions ? '按保存布局出图' : '重新排版'

  const renderDraft = useCallback(async (snapshot: SpecDraft, positions?: DiagramPositions, commit?: () => boolean) => {
    if (submitting.current) return false
    if (!token) {
      setError({ title: '需要先登录', detail: '登录后才能排版出图。', action: 'login' })
      return false
    }
    // 校验错误已由上方校验条展示，不再叠一条同义错误
    if (validateSpec(snapshot).some((issue) => issue.level === 'error')) return false
    const targetFormat = format
    submitting.current = true
    setLoading(true)
    setError(null)
    try {
      const response = await renderSpec(toJsonSpec(snapshot, positions), targetFormat, ratio, token)
      if (commit && !commit()) return false
      const nextPositions = positions && Object.fromEntries(
        snapshot.entities.map(({ id, name }) => [id, positions[name.trim()]]),
      )
      setPositionsById((current) => current === positionsById ? nextPositions : current)
      const nextResult: RenderResult = {
        format: targetFormat,
        ratio,
        signature: `${signatureOf(snapshot, positions)}|${targetFormat}`,
        renderedAt: Date.now(),
        overview: response.overview,
        entities: response.entities,
        layout: response.layout,
      }
      originalResult.current = nextResult
      setResult(nextResult)
      setTab((previous) =>
        previous === 'overview' || response.entities.some((entry) => entry.entity === previous) ? previous : 'overview',
      )
      return true
    } catch (caught) {
      // 失败时不动 result，上一次成功的预览继续留在右侧
      const detail = caught instanceof ApiError ? caught.message : ((caught as Error)?.message ?? '未知错误')
      const needLogin = caught instanceof ApiError && caught.status === 401
      setError({
        title: needLogin ? '需要先登录' : '排版没有完成',
        detail,
        action: needLogin ? 'login' : undefined,
        keptPreview: true,
      })
      return false
    } finally {
      submitting.current = false
      setLoading(false)
    }
  }, [format, positionsById, ratio, token])

  const handleRender = (positions?: DiagramPositions) => {
    if (!generatingRef.current) return renderDraft(spec, positions)
  }

  const layoutPositions = (): DiagramPositions => Object.fromEntries(
    result?.layout?.entities.map(({ entity, x, y }) => [entity, [x, y]]) ?? [],
  )

  const applyRatio = async () => {
    if (!originalResult.current || !ratioPending || submitting.current || generatingRef.current) return
    submitting.current = true
    setLoading(true)
    setError(null)
    try {
      setResult(await reframeDiagrams(originalResult.current, ratio))
    } catch (caught) {
      setError({
        title: '比例没能应用',
        detail: (caught as Error).message || '请稍后重试。',
        keptPreview: true,
      })
    } finally {
      submitting.current = false
      setLoading(false)
    }
  }

  const renderCurrent = () => {
    if (ratioOnly) void applyRatio()
    else void handleRender(savedPositions)
  }
  const resetLayout = async () => {
    if (await handleRender()) setTab('overview')
  }

  const moveEntity = (entity: string, x: number, y: number) => {
    if (stale || !result?.layout) return
    const positions = layoutPositions()
    positions[entity] = [x, y]
    void handleRender(positions)
  }

  /** 新图成功后一起更新草稿和预览。首次出图失败时仍可编辑已生成的规格。 */
  const handleGenerate = useCallback(async () => {
    if (generatingRef.current || submitting.current) return
    if (!token) {
      setDescribeError(null)
      setError({ title: '需要先登录', detail: '登录后才能用模型生成 E-R 图。', action: 'login' })
      return
    }

    const text = describe.trim()
    const submittedVersion = descriptionVersion.current
    const length = Array.from(text).length
    if (length === 0) {
      setDescribeError('先写一段系统描述，再点「生成 E-R 图」。')
      return
    }
    if (length > DESCRIBE_LIMIT) {
      setDescribeError(`描述最多 ${DESCRIBE_LIMIT} 字，当前 ${length} 字，请精简后再生成。`)
      return
    }
    if (!emptyDraft && (spec !== lastGeneratedSpec.current || savedPositions)) {
      const summary = `${spec.entities.length} 个实体、${spec.relations.length} 条联系`
      const confirmed = window.confirm(
        `新图生成后将替换当前草稿（${summary}）。要继续生成吗？`,
      )
      if (!confirmed) {
        setNotice({ title: '已取消替换，当前草稿没有变化。', items: [] })
        return
      }
    }

    generatingRef.current = true
    setGenerating(true)
    setDescribeError(null)
    setError(null)
    setNotice(null)
    try {
      const rawSpec = await generateSpec(text, token)
      const parsed = parseSpec(rawSpec)
      if (!parsed.ok) {
        setError({
          title: '模型规格不可用',
          detail: parsed.error.replace(/\s*当前草稿和预览都已保留。?\s*$/, '').trim() || '请调整描述后重试。',
          action: 'channel',
          keptPreview: true,
        })
        return
      }
      let cancelled = false
      const adoptSpec = () => {
        setSpec(parsed.spec)
        setPositionsById(undefined)
        setTab('overview')
      }
      const rendered = await renderDraft(parsed.spec, undefined, () => {
        if (currentSpec.current !== spec && !window.confirm('等待生成时草稿有更新。要用新图替换当前草稿吗？')) {
          cancelled = true
          return false
        }
        adoptSpec()
        lastGeneratedSpec.current = parsed.spec
        return true
      })
      if (cancelled) {
        setNotice({ title: '已取消替换，保留当前草稿。', items: [] })
        return
      }
      if (!rendered && (!emptyDraft || currentSpec.current !== spec)) return
      if (!rendered) adoptSpec()
      if (rendered && descriptionVersion.current === submittedVersion) setDescribe('')
      setNotice({
        title: `已生成${rendered ? ' E-R 图' : '可编辑规格'}：${parsed.spec.entities.length} 个实体、${parsed.spec.relations.length} 条联系`,
        items: [rendered ? '可直接输入下一份系统描述。' : '生成的规格已保留，修正后可点「重新排版」。', ...parsed.notices],
        action: rendered
          ? {
              label: '查看生成结果',
              run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
            }
          : undefined,
      })
    } catch (caught) {
      const detail = caught instanceof ApiError ? caught.message : ((caught as Error)?.message ?? '未知错误')
      const needLogin = caught instanceof ApiError && caught.status === 401
      setError({
        title: needLogin ? '需要先登录' : '生成没有完成',
        detail,
        action: needLogin ? 'login' : 'channel',
        keptPreview: true,
      })
    } finally {
      generatingRef.current = false
      setGenerating(false)
    }
  }, [describe, spec, emptyDraft, savedPositions, renderDraft, token])

  // 失败提示在编辑区顶部，用户可能正看着下方的预览，自动滚回顶部让整条提示可见
  useEffect(() => {
    if (!error) return
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [error])

  const dismissError = () => setError(null)

  const channelHintLabel = activeChannel
    ? `${activeChannel.name}${activeChannel.ready ? '' : '（未齐）'} · 检查渠道`
    : '去接入渠道'

  const loggedIn = !!token

  const changeDescribe = (value: string) => {
    descriptionVersion.current += 1
    setDescribe(value)
    if (describeError) setDescribeError(null)
  }

  const replaceEntity = (next: EntityDraft) =>
    setSpec((current) => ({
      ...current,
      entities: current.entities.map((entity) => (entity.id === next.id ? next : entity)),
    }))

  const replaceRelation = (next: RelationDraft) =>
    setSpec((current) => ({
      ...current,
      relations: current.relations.map((relation) => (relation.id === next.id ? next : relation)),
    }))

  const addEntity = () =>
    setSpec((current) => ({
      ...current,
      entities: [...current.entities, newEntity(uniqueName('实体', current.entities.map((entity) => entity.name)))],
    }))

  const removeEntity = (target: EntityDraft) => {
    const affected = spec.relations.filter((relation) => relation.ends.some((end) => end.entityId === target.id))
    if (affected.length) {
      const name = target.name.trim() || '未命名实体'
      const confirmed = window.confirm(
        `删除实体「${name}」？有 ${affected.length} 条联系引用了它，删除后这些端点需要重新选择实体。`,
      )
      if (!confirmed) return
    }
    setSpec((current) => ({
      ...current,
      entities: current.entities.filter((entity) => entity.id !== target.id),
      relations: current.relations.map((relation) => ({
        ...relation,
        ends: relation.ends.map((end) =>
          end.entityId === target.id ? { ...end, entityId: '', missingName: target.name } : end,
        ),
      })),
    }))
  }

  const addRelation = () =>
    setSpec((current) =>
      current.entities.length < 2 ? current : { ...current, relations: [...current.relations, newRelation(current)] },
    )

  const removeRelation = (target: RelationDraft) =>
    setSpec((current) => ({ ...current, relations: current.relations.filter((relation) => relation.id !== target.id) }))

  const handleLoadSample = async () => {
    if (generatingRef.current || submitting.current) return
    if (!emptyDraft) {
      const summary = `${spec.entities.length} 个实体、${spec.relations.length} 条联系`
      const confirmed = window.confirm(
        `用选课样例替换当前草稿？当前草稿有 ${summary}，替换后只能靠「导入 JSON」或重新编辑找回。`,
      )
      if (!confirmed) {
        setNotice({ title: '已取消替换，当前草稿没有变化。', items: [] })
        return
      }
    }
    const sample = readSample()
    setSpec(sample.spec)
    setPositionsById(undefined)
    setResult(null)
    setError(null)
    setTab('overview')
    lastGeneratedSpec.current = sample.spec
    // 样例不依赖模型渠道；已登录则直接出图，避免「有规格却空白」
    const rendered = token ? await renderDraft(sample.spec) : false
    setNotice({
      title: rendered
        ? `已载入选课样例并出图：${sample.spec.entities.length} 个实体、${sample.spec.relations.length} 条联系`
        : `已载入选课样例：${sample.spec.entities.length} 个实体、${sample.spec.relations.length} 条联系`,
      items: rendered
        ? sample.notices
        : [token ? '规格已就绪，点预览区「重新排版」即可出图。' : '规格已写入，登录后即可出图。', ...sample.notices],
      action: token
        ? {
            label: '查看预览区',
            run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
          }
        : { label: '去登录', run: onLogin },
    })
  }

  const loadSampleRef = useRef(handleLoadSample)
  loadSampleRef.current = handleLoadSample

  // 欢迎页的两个按钮：进入工作台后聚焦描述框，或直接载入样例
  useEffect(() => {
    if (!command) return
    if (command.type === 'sample') {
      loadSampleRef.current()
      return
    }
    const input = document.querySelector<HTMLTextAreaElement>('[data-testid="describe-input"]')
    if (!input) return
    input.focus({ preventScroll: true })
    input.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [command])

  const importFile = async (file: File) => {
    if (generatingRef.current || submitting.current) return
    let text: string
    try {
      text = await file.text()
    } catch {
      setError({ title: '导入没有完成', detail: '读取文件失败，请重新选择文件。' })
      return
    }
    let raw: unknown
    try {
      raw = JSON.parse(text)
    } catch (caught) {
      setError({
        title: '导入没有完成',
        detail: `${file.name} 不是合法 JSON（${(caught as Error).message}）。`,
        keptPreview: true,
      })
      return
    }
    const parsed = parseSpec(raw)
    if (!parsed.ok) {
      setError({
        title: '导入没有完成',
        detail: parsed.error.replace(/\s*当前编辑内容和预览都已保留。?\s*$/, '').trim() || '规格无法使用。',
        keptPreview: true,
      })
      return
    }
    setSpec(parsed.spec)
    setPositionsById(parsed.positionsById)
    setResult(null)
    setError(null)
    setTab('overview')
    lastGeneratedSpec.current = parsed.spec
    // positionsById 按实体 id；renderDraft 要按实体名；坐标不全则自动排版
    const namedEntries = parsed.positionsById
      ? parsed.spec.entities
          .map(({ id, name }) => {
            const point = parsed.positionsById?.[id]
            return point ? ([name.trim(), point as [number, number]] as const) : null
          })
          .filter((entry): entry is readonly [string, [number, number]] => !!entry)
      : []
    const namedPositions =
      namedEntries.length > 0 && namedEntries.length === parsed.spec.entities.length
        ? Object.fromEntries(namedEntries)
        : undefined
    const rendered = token ? await renderDraft(parsed.spec, namedPositions) : false
    setNotice({
      title: rendered
        ? `已导入 ${file.name} 并出图：${parsed.spec.entities.length} 个实体、${parsed.spec.relations.length} 条联系`
        : `已导入 ${file.name}：${parsed.spec.entities.length} 个实体、${parsed.spec.relations.length} 条联系`,
      items: rendered
        ? parsed.notices
        : [
            token ? '规格已就绪，点预览区「重新排版」即可出图。' : '规格已写入，登录后即可出图。',
            ...parsed.notices,
          ],
      action: token
        ? {
            label: '查看预览区',
            run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
          }
        : { label: '去登录', run: onLogin },
    })
  }

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    // 清空 value，才能重复选择同一个文件
    event.target.value = ''
    if (file) void importFile(file)
  }

  const handleExport = () => {
    const payload = toJsonSpec(spec, savedPositions)
    const name = `${safeFileName(spec.title.trim() || 'er-spec')}.json`
    downloadText(name, `${JSON.stringify(payload, null, 2)}\n`)
    setNotice({
      title: `已导出 ${name}`,
      items: [savedPositions
        ? '已保存当前规格和实体位置，再次导入可恢复布局。'
        : '已保存当前规格，再次导入后可自动排版。'],
    })
  }

  const handleDownload = (url: string, filename: string) => downloadDataUrl(url, filename)

  const handleDownloadAll = () => {
    if (!result) return
    const images = [result.overview, ...result.entities]
    images.forEach((image, index) => {
      window.setTimeout(() => downloadDataUrl(image.url, image.filename), index * 400)
    })
  }

  return (
    <div className="app">
      <header className="topbar">
        <a
          className="brand"
          href="/"
          onClick={(event) => {
            event.preventDefault()
            onHome()
          }}
          title="返回欢迎页"
          data-testid="go-home"
        >
          <BrandMark />
          <div className="brand-text">
            <h1>ERFlow 工作台</h1>
            <p>描述需求，生成可编辑的 E-R 图与实体属性图</p>
          </div>
        </a>

        <div className="toolbar">
          <input
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={handleFileChange}
            data-testid="file-input"
          />

          {(generating || loading) && (
            <span className="wb-busy" data-testid="wb-busy" role="status">
              <span className="spinner spinner-sm spinner-accent" aria-hidden="true" />
              {loading ? '排版中' : '生成中'}
            </span>
          )}

          {!emptyDraft && (
            <button
              type="button"
              className={loading || generating ? 'btn btn-primary is-busy' : blocked ? 'btn' : 'btn btn-primary'}
              onClick={renderCurrent}
              disabled={loading || generating || blocked}
              title={blocked ? '先修正左侧标出的问题' : '把当前规格提交给后端排版'}
              data-testid="render"
              aria-busy={loading || generating}
            >
              {loading ? (
                <>
                  <span className="spinner spinner-sm" aria-hidden="true" />
                  排版中…
                </>
              ) : generating ? (
                <>
                  <span className="spinner spinner-sm" aria-hidden="true" />
                  生成中…
                </>
              ) : (
                renderLabel
              )}
            </button>
          )}

          <button
            type="button"
            className={
              'wb-channel' +
              (activeChannel?.ready ? ' is-ready' : activeChannel ? ' is-warn' : ' is-idle')
            }
            onClick={onOpenApiPlatform}
            title={
              activeChannel
                ? `${activeChannel.name} · ${activeChannel.model || '未填模型'} — 打开 API 平台`
                : '打开 API 平台，接入模型渠道'
            }
            data-testid="open-api-platform"
            data-provider={activeChannel?.preset || undefined}
          >
            {activeChannel ? (
              <ProviderIcon id={activeChannel.preset} size={15} className="wb-channel-logo" />
            ) : null}
            <span className="wb-channel-copy">
              <em>
                {activeChannel?.ready ? '已接通' : activeChannel ? '待齐' : username ? '未接线' : 'API 平台'}
              </em>
              <strong>
                {activeChannel
                  ? activeChannel.name
                  : username
                    ? '去接入渠道'
                    : '模型渠道'}
              </strong>
            </span>
          </button>
          <button type="button" className="btn btn-ghost" onClick={onUsage}>Token 用量</button>
          {!username && (
            <button type="button" className="btn btn-primary" onClick={onLogin} data-testid="login-entry">
              登录
            </button>
          )}
        </div>
      </header>

      <main className="workspace">
        {(error || errors.length > 0 || notice || warnings.length > 0) && (
          <div className="messages">
            {error && (
              <div
                className={`banner banner-error${error.action === 'channel' ? ' has-channel' : ''}`}
                role="alert"
                data-testid="error-banner"
              >
                <div className="banner-body">
                  <strong>{error.title}</strong>
                  <p className="banner-text">{error.detail}</p>
                  {error.keptPreview && result && (
                    <p className="banner-sub">上次成功的预览仍保留。</p>
                  )}
                  {error.action === 'channel' && (
                    <button
                      type="button"
                      className="banner-channel"
                      onClick={onOpenApiPlatform}
                      data-testid="error-channel-hint"
                    >
                      {activeChannel ? (
                        <ProviderIcon id={activeChannel.preset} size={14} className="banner-channel-logo" />
                      ) : null}
                      <span>{channelHintLabel}</span>
                    </button>
                  )}
                  {error.action === 'login' && (
                    <button
                      type="button"
                      className="btn btn-sm banner-action"
                      onClick={onLogin}
                      data-testid="error-login-hint"
                    >
                      去登录
                    </button>
                  )}
                </div>
                <button type="button" className="icon-btn" onClick={dismissError} aria-label="关闭错误提示">
                  ×
                </button>
              </div>
            )}

            {!error && errors.length > 0 && (
              <div className="banner banner-warn" data-testid="validation-banner">
                <div className="banner-body">
                  <strong>还有 {errors.length} 处要改，改完才能排版</strong>
                  <ul className="banner-list">
                    {errors.slice(0, 6).map((issue, index) => (
                      <li key={index}>{issue.message}</li>
                    ))}
                  </ul>
                  {errors.length > 6 && <p className="banner-sub">另有 {errors.length - 6} 条未展开。</p>}
                </div>
              </div>
            )}

            {errors.length === 0 && warnings.length > 0 && (
              <div className="banner banner-muted">
                <div className="banner-body">
                  <strong>现在可以排版，另有 {warnings.length} 处提醒</strong>
                  <ul className="banner-list">
                    {warnings.slice(0, 4).map((issue, index) => (
                      <li key={index}>{issue.message}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {notice && (
              <div className="banner banner-info" data-testid="notice-banner">
                <div className="banner-body">
                  <strong>{notice.title}</strong>
                  {notice.items.length > 0 && (
                    <ul className="banner-list">
                      {notice.items.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  )}
                  {notice.action && (
                    <button
                      type="button"
                      className="btn btn-sm banner-action"
                      onClick={notice.action.run}
                      data-testid="notice-action"
                    >
                      {notice.action.label}
                    </button>
                  )}
                </div>
                <button type="button" className="icon-btn" onClick={() => setNotice(null)} aria-label="关闭提示">
                  ×
                </button>
              </div>
            )}
          </div>
        )}

        <div className="columns">
          <section className={`panel editor${emptyDraft && !manualOpen ? ' is-cold' : ''}`}>
            <div className="panel-head">
              <h2>{emptyDraft && !manualOpen ? '开始' : '规格'}</h2>
              {!(emptyDraft && !manualOpen) && (
                <span className="muted">
                  {spec.entities.length} 实体 · {spec.relations.length} 联系
                </span>
              )}
              <div className="panel-tools">
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => fileInput.current?.click()}
                  data-testid="import-json"
                >
                  导入 JSON
                </button>
                {!(emptyDraft && !manualOpen) && (
                  <>
                    <span className="tool-sep" aria-hidden="true">
                      |
                    </span>
                    <button
                      type="button"
                      className="link-btn"
                      onClick={handleExport}
                      disabled={emptyDraft}
                      data-testid="export-json"
                    >
                      导出 JSON
                    </button>
                    <SpecSearch spec={spec} onSelect={locateSpec} />
                  </>
                )}
              </div>
            </div>

            <div className="panel-body">
              <DescribeBox
                text={describe}
                onTextChange={changeDescribe}
                onGenerate={() => void handleGenerate()}
                generating={generating}
                rendering={loading}
                replacing={!emptyDraft}
                ratio={ratio}
                onRatioChange={setRatio}
                error={describeError}
                channelLabel={
                  activeChannel?.ready
                    ? `生成将走 · ${activeChannel.name}`
                    : activeChannel
                      ? `渠道未齐 · ${activeChannel.name}`
                      : null
                }
                onOpenChannel={onOpenApiPlatform}
                onLoadSample={() => void handleLoadSample()}
                loggedIn={loggedIn}
                onLogin={onLogin}
              />

              {emptyDraft && !manualOpen ? (
                <div className="cold-manual">
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => setManualOpen(true)}
                    data-testid="open-manual-edit"
                  >
                    或手动添加实体 / 联系
                  </button>
                </div>
              ) : (
                <>
                  <div className="spec-band">
                    <label className="field spec-title-field">
                      <span className="field-label">课题标题</span>
                      <input
                        className="input"
                        value={spec.title}
                        placeholder="如：学生选课系统"
                        onChange={(event) => setSpec((current) => ({ ...current, title: event.target.value }))}
                        data-testid="title-input"
                      />
                    </label>

                    <div className="section-head">
                      <h3>
                        实体 <span className="count">{spec.entities.length}</span>
                      </h3>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={addEntity}
                        disabled={spec.entities.length >= LIMITS.entities}
                        data-testid="add-entity"
                      >
                        + 添加实体
                      </button>
                    </div>

                    {spec.entities.length === 0 ? (
                      <p className="hint spec-empty">生成后出现在这里，也可手动添加。</p>
                    ) : (
                      <div className="card-list">
                        {spec.entities.map((entity, index) => (
                          <EntityCard
                            key={entity.id}
                            entity={entity}
                            index={index}
                            locatedId={locatedId}
                            relationCount={
                              spec.relations.filter((relation) =>
                                relation.ends.some((end) => end.entityId === entity.id),
                              ).length
                            }
                            onChange={replaceEntity}
                            onRemove={() => removeEntity(entity)}
                          />
                        ))}
                      </div>
                    )}

                    <div className="section-head">
                      <h3>
                        联系 <span className="count">{spec.relations.length}</span>
                      </h3>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={addRelation}
                        disabled={spec.entities.length < 2 || spec.relations.length >= LIMITS.relations}
                        title={spec.entities.length < 2 ? '至少要有两个实体才能建联系' : undefined}
                        data-testid="add-relation"
                      >
                        + 添加联系
                      </button>
                    </div>

                    {spec.relations.length === 0 ? (
                      <p className="hint spec-empty">
                        {spec.entities.length < 2 ? '至少两个实体后可添加联系。' : '添加联系，或生成后自动出现。'}
                      </p>
                    ) : (
                      <div className="card-list">
                        {spec.relations.map((relation, index) => (
                          <RelationCard
                            key={relation.id}
                            relation={relation}
                            index={index}
                            locatedId={locatedId}
                            entities={spec.entities}
                            onChange={replaceRelation}
                            onRemove={() => removeRelation(relation)}
                          />
                        ))}
                      </div>
                    )}

                    <p className="foot-note">
                      上限：实体 {LIMITS.entities} · 联系 {LIMITS.relations} · 属性 {LIMITS.attrs} · 名称{' '}
                      {LIMITS.label} 字
                    </p>
                  </div>
                </>
              )}
            </div>
          </section>

          <PreviewPanel
            result={result}
            loading={loading}
            generating={generating}
            emptyDraft={emptyDraft}
            stale={stale}
            blocked={blocked}
            tab={tab}
            onTabChange={setTab}
            onRender={renderCurrent}
            onResetLayout={() => void resetLayout()}
            onMoveEntity={moveEntity}
            formatOnly={formatOnly}
            hasSavedLayout={!!savedPositions}
            renderLabel={renderLabel}
            format={format}
            onFormatChange={setFormat}
            ratio={ratio}
            ratioPending={ratioPending}
            onRatioChange={setRatio}
            onApplyRatio={() => void applyRatio()}
            onDownloadAll={handleDownloadAll}
            onDownloadOne={handleDownload}
            onLoadSample={() => void handleLoadSample()}
            loggedIn={loggedIn}
            onLogin={onLogin}
          />
        </div>
      </main>

    </div>
  )
}

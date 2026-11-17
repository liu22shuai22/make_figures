import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import EntityCard from './components/EntityCard'
import RelationCard from './components/RelationCard'
import SpecSearch from './components/SpecSearch'
import PreviewPanel from './components/PreviewPanel'
import DescribeBox, { DESCRIBE_LIMIT } from './components/DescribeBox'
import type { AssistantDraft } from './components/ModelAssistant'
import DiagramKindSwitch from './components/DiagramKindSwitch'
import ActorCard from './components/ActorCard'
import UseCaseCard from './components/UseCaseCard'
import UseCaseLinkCard from './components/UseCaseLinkCard'
import UseCaseDepCard from './components/UseCaseDepCard'
import { reframeDiagrams } from './canvasRatio'
import BrandMark from './components/BrandMark'
import ProviderIcon from './components/ProviderIcon'
import { useLocale } from './LocaleContext'
import { ApiError, generateSpec, generateUseCaseSpec, renderSpec, renderUseCaseSpec, reviewUseCaseSpec } from './api'
import UseCaseReviewPanel, { type UseCaseReviewOutcome } from './components/UseCaseReviewPanel'
import { fetchProviders, type ProviderPublic } from './providersApi'
import { downloadDataUrl, downloadText, safeFileName } from './download'
import { SAMPLE_JSON } from './sample'
import { USECASE_SAMPLE_JSON } from './usecaseSample'
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
import {
  EMPTY_USECASE_SPEC,
  USECASE_LIMITS,
  newActor,
  newUseCase,
  newUseCaseDep,
  newUseCaseLink,
  parseUseCaseSpec,
  signatureOfUseCase,
  toUseCaseJson,
  uniqueName as uniqueUseCaseName,
  validateUseCaseSpec,
} from './usecaseSpec'
import type {
  ActorDraft,
  CanvasRatio,
  DiagramKind,
  DiagramPositions,
  EntityDraft,
  ImageFormat,
  RelationDraft,
  RenderResult,
  SpecDraft,
  UseCaseDepDraft,
  UseCaseDraft,
  UseCaseLinkDraft,
  UseCaseSpecDraft,
  WorkbenchCommand,
} from './types'

interface Notice {
  title: string
  items: string[]
  /** 提示条上的快捷入口，例如生成成功后的「查看生成结果」 */
  action?: { label: string; run: () => void }
}

interface DraftReview {
  draft: UseCaseSpecDraft
  text: string
  outcome: UseCaseReviewOutcome | null
}

async function requestUseCaseReview(
  text: string,
  draft: UseCaseSpecDraft,
  token: string,
  unavailable: string,
): Promise<UseCaseReviewOutcome> {
  try {
    return await reviewUseCaseSpec(text, toUseCaseJson(draft), token)
  } catch (error) {
    return { status: 'error', detail: error instanceof ApiError ? error.message : unavailable }
  }
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

function readUseCaseSample(): { spec: UseCaseSpecDraft; notices: string[] } {
  const parsed = parseUseCaseSpec(USECASE_SAMPLE_JSON)
  if (parsed.ok) return { spec: parsed.spec, notices: parsed.notices }
  return { spec: EMPTY_USECASE_SPEC, notices: [] }
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
  const { app: t } = useLocale()
  const copy = useRef(t)
  copy.current = t
  const [diagramKind, setDiagramKind] = useState<DiagramKind>('er')
  const isUseCase = diagramKind === 'usecase'

  const [spec, setSpec] = useState<SpecDraft>(EMPTY_SPEC)
  const [ucSpec, setUcSpec] = useState<UseCaseSpecDraft>(EMPTY_USECASE_SPEC)
  const [ucReview, setUcReview] = useState<DraftReview | null>(null)
  const [positionsById, setPositionsById] = useState<DiagramPositions>()
  const [ucPositionsById, setUcPositionsById] = useState<DiagramPositions>()
  const [format, setFormat] = useState<ImageFormat>('png')
  const [ratio, setRatio] = useState<CanvasRatio>('auto')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<RenderResult | null>(null)
  const [ucResult, setUcResult] = useState<RenderResult | null>(null)
  const [error, setError] = useState<WorkbenchError | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [tab, setTab] = useState('overview')
  const [locatedId, setLocatedId] = useState<string>()

  /** 自然语言生成（E-R / 用例各自保留描述） */
  const [describe, setDescribe] = useState('')
  const [ucDescribe, setUcDescribe] = useState('')
  const [describeError, setDescribeError] = useState<string | null>(null)
  const [ucDescribeError, setUcDescribeError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [activeChannel, setActiveChannel] = useState<ProviderPublic | null>(null)
  /** 空草稿时默认收起手动编辑区，避免冷启动被实体/联系空壳占满 */
  const [manualOpen, setManualOpen] = useState(false)
  const [ucManualOpen, setUcManualOpen] = useState(false)

  const fileInput = useRef<HTMLInputElement>(null)

  function attachUseCaseReview(text: string, draft: UseCaseSpecDraft, result: Promise<UseCaseReviewOutcome>) {
    const pending: DraftReview = { draft, text, outcome: null }
    setUcReview(pending)
    void result.then((outcome) => {
      setUcReview((current) => current === pending ? { ...pending, outcome } : current)
    })
  }

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
  const originalUcResult = useRef<RenderResult | null>(null)
  const currentSpec = useRef(spec)
  const currentUcSpec = useRef(ucSpec)
  const lastGeneratedSpec = useRef<SpecDraft | null>(null)
  const lastGeneratedUcSpec = useRef<UseCaseSpecDraft | null>(null)
  const descriptionVersion = useRef(0)
  useLayoutEffect(() => { currentSpec.current = spec }, [spec])
  useLayoutEffect(() => { currentUcSpec.current = ucSpec }, [ucSpec])

  const locateSpec = useCallback((id: string) => {
    const target = document.getElementById(`spec-${id}`)
    if (!target) return
    setLocatedId(id)
    target.focus({ preventScroll: true })
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    target.scrollIntoView({ behavior: reduceMotion ? 'instant' : 'smooth', block: 'center', inline: 'nearest' })
  }, [])

  const emptyErDraft = !spec.title.trim() && !spec.entities.length && !spec.relations.length
  const emptyUcDraft =
    !ucSpec.title.trim() &&
    !ucSpec.system.trim() &&
    !ucSpec.actors.length &&
    !ucSpec.useCases.length &&
    !ucSpec.links.length &&
    !ucSpec.dependencies.length
  const emptyDraft = isUseCase ? emptyUcDraft : emptyErDraft
  const activeManualOpen = isUseCase ? ucManualOpen : manualOpen

  const erIssues = useMemo(() => (emptyErDraft ? [] : validateSpec(spec)), [spec, emptyErDraft])
  const ucIssues = useMemo(() => (emptyUcDraft ? [] : validateUseCaseSpec(ucSpec)), [ucSpec, emptyUcDraft])
  const issues = isUseCase ? ucIssues : erIssues
  useLayoutEffect(() => {
    if (isUseCase) {
      onAssistantDraft({ spec: EMPTY_SPEC, issues: [], onLocate: locateSpec })
      return
    }
    onAssistantDraft({ spec, issues: erIssues, onLocate: locateSpec })
  }, [isUseCase, spec, erIssues, locateSpec, onAssistantDraft])
  const errors = useMemo(() => issues.filter((issue) => issue.level === 'error'), [issues])
  const warnings = useMemo(() => issues.filter((issue) => issue.level === 'warn'), [issues])
  const blocked = isUseCase
    ? !ucSpec.actors.length || !ucSpec.useCases.length || errors.length > 0
    : !spec.entities.length || errors.length > 0

  const savedPositions = useMemo<DiagramPositions | undefined>(() => {
    const entities = spec.entities
    if (!positionsById || Object.keys(positionsById).length !== entities.length
        || entities.some(({ id }) => !positionsById[id])) return undefined
    return Object.fromEntries(entities.map(({ name, id }) => [name.trim(), positionsById[id]]))
  }, [spec.entities, positionsById])
  const ucNodeIds = useMemo(
    () => [...ucSpec.actors.map((actor) => ({ id: actor.id, name: actor.name })),
      ...ucSpec.useCases.map((item) => ({ id: item.id, name: item.name }))],
    [ucSpec.actors, ucSpec.useCases],
  )
  const savedUcPositions = useMemo<DiagramPositions | undefined>(() => {
    if (!ucPositionsById || Object.keys(ucPositionsById).length !== ucNodeIds.length
        || ucNodeIds.some(({ id }) => !ucPositionsById[id])) return undefined
    return Object.fromEntries(ucNodeIds.map(({ name, id }) => [name.trim(), ucPositionsById[id]]))
  }, [ucNodeIds, ucPositionsById])
  const draftSignature = useMemo(() => signatureOf(spec, savedPositions), [spec, savedPositions])
  const ucDraftSignature = useMemo(() => signatureOfUseCase(ucSpec, savedUcPositions), [ucSpec, savedUcPositions])
  const activeResult = isUseCase ? ucResult : result
  const sameDraft = isUseCase
    ? ucResult !== null && ucResult.signature === `${ucDraftSignature}|${ucResult.format}`
    : result !== null && result.signature === `${draftSignature}|${result.format}`
  const ratioPending = activeResult !== null && activeResult.ratio !== ratio
  const stale = activeResult !== null && (!sameDraft || activeResult.format !== format || ratioPending)
  const activeSavedPositions = isUseCase ? savedUcPositions : savedPositions
  const formatOnly = sameDraft && !!activeSavedPositions && !ratioPending && !!activeResult && activeResult.format !== format
  const ratioOnly = sameDraft && ratioPending && !!activeResult && activeResult.format === format
  const renderLabel = ratioOnly
    ? t.applyRatio
    : formatOnly
      ? t.updateFormat
      : activeSavedPositions
        ? t.renderSaved
        : t.reLayout

  const renderDraft = useCallback(async (snapshot: SpecDraft, positions?: DiagramPositions, commit?: () => boolean) => {
    if (submitting.current) return false
    if (!token) {
      setError({ title: copy.current.needLogin, detail: copy.current.needLoginRender, action: 'login' })
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
      const detail = caught instanceof ApiError ? caught.message : ((caught as Error)?.message ?? copy.current.unknownError)
      const needLogin = caught instanceof ApiError && caught.status === 401
      setError({
        title: needLogin ? copy.current.needLogin : copy.current.layoutFailed,
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
    const source = isUseCase ? originalUcResult.current : originalResult.current
    if (!source || !ratioPending || submitting.current || generatingRef.current) return
    submitting.current = true
    setLoading(true)
    setError(null)
    try {
      const next = await reframeDiagrams(source, ratio)
      if (isUseCase) setUcResult(next)
      else setResult(next)
    } catch (caught) {
      setError({
        title: copy.current.ratioFailed,
        detail: (caught as Error).message || copy.current.retryLater,
        keptPreview: true,
      })
    } finally {
      submitting.current = false
      setLoading(false)
    }
  }

  const renderUseCaseDraft = useCallback(async (
    snapshot: UseCaseSpecDraft,
    positions?: DiagramPositions,
    commit?: () => boolean,
  ) => {
    if (submitting.current) return false
    if (!token) {
      setError({ title: copy.current.needLogin, detail: copy.current.needLoginUcRender, action: 'login' })
      return false
    }
    if (validateUseCaseSpec(snapshot).some((issue) => issue.level === 'error')) return false
    const targetFormat = format
    submitting.current = true
    setLoading(true)
    setError(null)
    try {
      const response = await renderUseCaseSpec(toUseCaseJson(snapshot, positions), targetFormat, ratio, token)
      if (commit && !commit()) return false
      const nodes = [
        ...snapshot.actors.map(({ id, name }) => ({ id, name })),
        ...snapshot.useCases.map(({ id, name }) => ({ id, name })),
      ]
      const nextPositions = positions && Object.fromEntries(
        nodes.map(({ id, name }) => [id, positions[name.trim()]]),
      )
      setUcPositionsById((current) => (current === ucPositionsById ? nextPositions : current))
      const nextResult: RenderResult = {
        format: targetFormat,
        ratio,
        signature: `${signatureOfUseCase(snapshot, positions)}|${targetFormat}`,
        renderedAt: Date.now(),
        overview: response.overview,
        entities: response.entities,
        layout: response.layout,
      }
      originalUcResult.current = nextResult
      setUcResult(nextResult)
      setTab('overview')
      return true
    } catch (caught) {
      const detail = caught instanceof ApiError ? caught.message : ((caught as Error)?.message ?? copy.current.unknownError)
      const needLogin = caught instanceof ApiError && caught.status === 401
      setError({
        title: needLogin ? copy.current.needLogin : copy.current.ucLayoutFailed,
        detail,
        action: needLogin ? 'login' : undefined,
        keptPreview: true,
      })
      return false
    } finally {
      submitting.current = false
      setLoading(false)
    }
  }, [format, ratio, token, ucPositionsById])

  const renderCurrent = () => {
    if (ratioOnly) void applyRatio()
    else if (isUseCase) void renderUseCaseDraft(ucSpec, savedUcPositions)
    else void handleRender(savedPositions)
  }
  const resetLayout = async () => {
    if (isUseCase) {
      setUcPositionsById(undefined)
      if (await renderUseCaseDraft(ucSpec)) setTab('overview')
      return
    }
    if (await handleRender()) setTab('overview')
  }

  const layoutUcPositions = (): DiagramPositions => Object.fromEntries(
    ucResult?.layout?.entities.map(({ entity, x, y }) => [entity, [x, y]]) ?? [],
  )

  const moveEntity = (entity: string, x: number, y: number) => {
    if (isUseCase) {
      if (stale || !ucResult?.layout) return
      const positions = layoutUcPositions()
      positions[entity] = [x, y]
      void renderUseCaseDraft(ucSpec, positions)
      return
    }
    if (stale || !result?.layout) return
    const positions = layoutPositions()
    positions[entity] = [x, y]
    void handleRender(positions)
  }

  const changeDiagramKind = (kind: DiagramKind) => {
    if (kind === diagramKind) return
    setDiagramKind(kind)
    setError(null)
    setNotice(null)
    setLocatedId(undefined)
    if (kind === 'er') setDescribeError(null)
    else setUcDescribeError(null)
  }

  /** 新图成功后一起更新草稿和预览。首次出图失败时仍可编辑已生成的规格。 */
  const handleGenerate = useCallback(async () => {
    if (generatingRef.current || submitting.current) return

    if (diagramKind === 'usecase') {
      if (!token) {
        setUcDescribeError(null)
        setError({ title: copy.current.needLogin, detail: copy.current.needLoginUcGen, action: 'login' })
        return
      }
      const text = ucDescribe.trim()
      const submittedVersion = descriptionVersion.current
      const length = Array.from(text).length
      if (length === 0) {
        setUcDescribeError(copy.current.describeEmptyUc)
        return
      }
      if (length > DESCRIBE_LIMIT) {
        setUcDescribeError(copy.current.describeOver(DESCRIBE_LIMIT, length))
        return
      }
      if (!emptyUcDraft && ucSpec !== lastGeneratedUcSpec.current) {
        const summary = copy.current.summaryUc(ucSpec.actors.length, ucSpec.useCases.length)
        const confirmed = window.confirm(copy.current.confirmReplaceUc(summary))
        if (!confirmed) {
          setNotice({ title: copy.current.cancelledKeep, items: [] })
          return
        }
      }

      generatingRef.current = true
      setGenerating(true)
      setUcDescribeError(null)
      setError(null)
      setNotice(null)
      try {
        const { spec: rawSpec, reviewNotes } = await generateUseCaseSpec(text, token)
        const parsed = parseUseCaseSpec(rawSpec)
        if (!parsed.ok) {
          setError({
            title: copy.current.modelSpecBad,
            detail: parsed.error || copy.current.adjustRetry,
            action: 'channel',
            keptPreview: true,
          })
          return
        }
        const review = requestUseCaseReview(text, parsed.spec, token, copy.current.reviewUnavailable)
        let cancelled = false
        const adoptSpec = () => {
          setUcSpec(parsed.spec)
          attachUseCaseReview(text, parsed.spec, review)
          lastGeneratedUcSpec.current = parsed.spec
          setUcPositionsById(undefined)
          setUcManualOpen(true)
          setTab('overview')
        }
        const rendered = await renderUseCaseDraft(parsed.spec, undefined, () => {
          if (
            currentUcSpec.current !== ucSpec &&
            !window.confirm(copy.current.confirmReplaceWhileWaiting)
          ) {
            cancelled = true
            return false
          }
          adoptSpec()
          return true
        })
        if (cancelled) {
          setNotice({ title: copy.current.cancelledKeepDraft, items: [] })
          return
        }
        const needsRestore = !rendered && (!emptyUcDraft || currentUcSpec.current !== ucSpec)
        if (!rendered && !needsRestore) adoptSpec()
        if (rendered && descriptionVersion.current === submittedVersion) setUcDescribe('')
        setNotice({
          title: copy.current.genUcDone(rendered, parsed.spec.actors.length, parsed.spec.useCases.length),
          items: [
            rendered ? '可直接输入下一份场景描述。' : needsRestore
              ? '这份新规格尚未出图。可载入表单编辑，右侧保留上次成功的图。'
              : '生成的规格已载入表单，编辑后可点「重新排版」。',
            ...reviewNotes.map((note) => copy.current.pendingConfirm(note)),
            ...parsed.notices,
          ],
          action: rendered
            ? {
                label: copy.current.viewResult,
                run: () =>
                  document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
              }
            : needsRestore ? {
                label: copy.current.loadGenerated,
                run: () => {
                  if (submitting.current || generatingRef.current || !window.confirm(copy.current.confirmLoadGenerated)) return
                  adoptSpec()
                  setNotice({ title: copy.current.loadedUcSpec, items: [...reviewNotes.map((note) => copy.current.pendingConfirm(note)), ...parsed.notices] })
                },
              } : undefined,
        })
      } catch (caught) {
        const detail = caught instanceof ApiError ? caught.message : ((caught as Error)?.message ?? copy.current.unknownError)
        const needLogin = caught instanceof ApiError && caught.status === 401
        setError({
          title: needLogin ? copy.current.needLogin : copy.current.genFailed,
          detail,
          action: needLogin ? 'login' : 'channel',
          keptPreview: true,
        })
      } finally {
        generatingRef.current = false
        setGenerating(false)
      }
      return
    }

    if (!token) {
      setDescribeError(null)
      setError({ title: copy.current.needLogin, detail: copy.current.needLoginErGen, action: 'login' })
      return
    }

    const text = describe.trim()
    const submittedVersion = descriptionVersion.current
    const length = Array.from(text).length
    if (length === 0) {
      setDescribeError(copy.current.describeEmptyEr)
      return
    }
    if (length > DESCRIBE_LIMIT) {
      setDescribeError(copy.current.describeOver(DESCRIBE_LIMIT, length))
      return
    }
    if (!emptyDraft && (spec !== lastGeneratedSpec.current || savedPositions)) {
      const summary = copy.current.summaryEr(spec.entities.length, spec.relations.length)
      const confirmed = window.confirm(copy.current.confirmReplaceEr(summary))
      if (!confirmed) {
        setNotice({ title: copy.current.cancelledKeep, items: [] })
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
          title: copy.current.modelSpecBad,
          detail: parsed.error.replace(/\s*当前草稿和预览都已保留。?\s*$/, '').trim() || copy.current.adjustRetry,
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
        if (currentSpec.current !== spec && !window.confirm(copy.current.confirmReplaceWhileWaiting)) {
          cancelled = true
          return false
        }
        adoptSpec()
        lastGeneratedSpec.current = parsed.spec
        return true
      })
      if (cancelled) {
        setNotice({ title: copy.current.cancelledKeepDraft, items: [] })
        return
      }
      if (!rendered && (!emptyDraft || currentSpec.current !== spec)) return
      if (!rendered) adoptSpec()
      if (rendered && descriptionVersion.current === submittedVersion) setDescribe('')
      setNotice({
        title: copy.current.genErDone(rendered, parsed.spec.entities.length, parsed.spec.relations.length),
        items: [rendered ? '可直接输入下一份系统描述。' : '生成的规格已保留，修正后可点「重新排版」。', ...parsed.notices],
        action: rendered
          ? {
              label: copy.current.viewResult,
              run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
            }
          : undefined,
      })
    } catch (caught) {
      const detail = caught instanceof ApiError ? caught.message : ((caught as Error)?.message ?? copy.current.unknownError)
      const needLogin = caught instanceof ApiError && caught.status === 401
      setError({
        title: needLogin ? copy.current.needLogin : copy.current.genFailed,
        detail,
        action: needLogin ? 'login' : 'channel',
        keptPreview: true,
      })
    } finally {
      generatingRef.current = false
      setGenerating(false)
    }
  }, [
    diagramKind,
    ucDescribe,
    describe,
    spec,
    ucSpec,
    emptyDraft,
    emptyUcDraft,
    savedPositions,
    renderDraft,
    renderUseCaseDraft,
    token,
  ])

  // 失败提示在编辑区顶部，用户可能正看着下方的预览，自动滚回顶部让整条提示可见
  useEffect(() => {
    if (!error) return
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [error])

  const dismissError = () => setError(null)

  const channelHintLabel = activeChannel
    ? (activeChannel.ready
        ? t.channelHintReady(activeChannel.name)
        : t.channelHintWarn(activeChannel.name))
    : t.channelHintIdle

  const loggedIn = !!token

  const changeDescribe = (value: string) => {
    descriptionVersion.current += 1
    if (isUseCase) {
      setUcDescribe(value)
      if (ucDescribeError) setUcDescribeError(null)
      return
    }
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

  const replaceActor = (next: ActorDraft) =>
    setUcSpec((current) => ({
      ...current,
      actors: current.actors.map((actor) => (actor.id === next.id ? next : actor)),
    }))

  const replaceUseCase = (next: UseCaseDraft) =>
    setUcSpec((current) => ({
      ...current,
      useCases: current.useCases.map((item) => (item.id === next.id ? next : item)),
    }))

  const replaceUseCaseLink = (next: UseCaseLinkDraft) =>
    setUcSpec((current) => ({
      ...current,
      links: current.links.map((link) => (link.id === next.id ? next : link)),
    }))

  const addActor = () =>
    setUcSpec((current) => ({
      ...current,
      actors: [
        ...current.actors,
        newActor(uniqueUseCaseName(copy.current.actorDefault, current.actors.map((actor) => actor.name))),
      ],
    }))

  const removeActor = (target: ActorDraft) => {
    if (generatingRef.current || submitting.current) return
    const linkCount = ucSpec.links.filter((link) => link.actorId === target.id).length
    if (linkCount > 0) {
      const confirmed = window.confirm(
        copy.current.confirmDelActor(target.name || copy.current.unnamed, linkCount),
      )
      if (!confirmed) return
    }
    setUcSpec((current) => ({
      ...current,
      actors: current.actors.filter((actor) => actor.id !== target.id),
      links: current.links.filter((link) => link.actorId !== target.id),
    }))
    setUcPositionsById(undefined)
  }

  const addUseCaseItem = () =>
    setUcSpec((current) => ({
      ...current,
      useCases: [
        ...current.useCases,
        newUseCase(uniqueUseCaseName(copy.current.useCaseDefault, current.useCases.map((item) => item.name))),
      ],
    }))

  const removeUseCaseItem = (target: UseCaseDraft) => {
    if (generatingRef.current || submitting.current) return
    const linkCount = ucSpec.links.filter((link) => link.useCaseId === target.id).length
    const depCount = ucSpec.dependencies.filter(
      (dep) => dep.fromId === target.id || dep.toId === target.id,
    ).length
    if (linkCount > 0 || depCount > 0) {
      const parts = [
        linkCount > 0 ? `${linkCount} 条关联` : '',
        depCount > 0 ? `${depCount} 条依赖` : '',
      ].filter(Boolean)
      const confirmed = window.confirm(
        `删除用例「${target.name || '未命名'}」？将一并清除 ${parts.join('、')}。`,
      )
      if (!confirmed) return
    }
    setUcSpec((current) => ({
      ...current,
      useCases: current.useCases.filter((item) => item.id !== target.id),
      links: current.links.filter((link) => link.useCaseId !== target.id),
      dependencies: current.dependencies.filter(
        (dep) => dep.fromId !== target.id && dep.toId !== target.id,
      ),
    }))
    setUcPositionsById(undefined)
  }

  const addUseCaseLinkItem = () =>
    setUcSpec((current) => {
      if (!current.actors.length || !current.useCases.length) return current
      return {
        ...current,
        links: [...current.links, newUseCaseLink(current.actors[0].id, current.useCases[0].id)],
      }
    })

  const removeUseCaseLinkItem = (target: UseCaseLinkDraft) =>
    setUcSpec((current) => ({
      ...current,
      links: current.links.filter((link) => link.id !== target.id),
    }))

  const replaceUseCaseDep = (next: UseCaseDepDraft) =>
    setUcSpec((current) => ({
      ...current,
      dependencies: current.dependencies.map((dep) => (dep.id === next.id ? next : dep)),
    }))

  const addUseCaseDepItem = () =>
    setUcSpec((current) => {
      if (current.useCases.length < 2) return current
      return {
        ...current,
        dependencies: [
          ...current.dependencies,
          newUseCaseDep('include', current.useCases[0].id, current.useCases[1].id),
        ],
      }
    })

  const removeUseCaseDepItem = (target: UseCaseDepDraft) =>
    setUcSpec((current) => ({
      ...current,
      dependencies: current.dependencies.filter((dep) => dep.id !== target.id),
    }))

  const addEntity = () =>
    setSpec((current) => ({
      ...current,
      entities: [...current.entities, newEntity(uniqueName(copy.current.entityDefault, current.entities.map((entity) => entity.name)))],
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

  const loadErSample = async () => {
    if (generatingRef.current || submitting.current) return
    if (!emptyErDraft) {
      const summary = `${spec.entities.length} 个实体、${spec.relations.length} 条联系`
      const confirmed = window.confirm(
        `用选课样例替换当前草稿？当前草稿有 ${summary}，替换后只能靠「导入 JSON」或重新编辑找回。`,
      )
      if (!confirmed) {
        setNotice({ title: copy.current.cancelledKeep, items: [] })
        return
      }
    }
    const sample = readSample()
    setDiagramKind('er')
    setSpec(sample.spec)
    setPositionsById(undefined)
    setResult(null)
    setError(null)
    setTab('overview')
    lastGeneratedSpec.current = sample.spec
    const rendered = token ? await renderDraft(sample.spec) : false
    setNotice({
      title: rendered
        ? copy.current.sampleLoadedEr(true, sample.spec.entities.length, sample.spec.relations.length)
        : copy.current.sampleLoadedEr(false, sample.spec.entities.length, sample.spec.relations.length),
      items: rendered
        ? sample.notices
        : [token ? '规格已就绪，点预览区「重新排版」即可出图。' : '规格已写入，登录后即可出图。', ...sample.notices],
      action: token
        ? {
            label: copy.current.viewPreview,
            run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
          }
        : { label: copy.current.goLogin, run: onLogin },
    })
  }

  const loadUseCaseSample = async () => {
    if (generatingRef.current || submitting.current) return
    if (!emptyUcDraft) {
      const summary = `${ucSpec.actors.length} 个参与者、${ucSpec.useCases.length} 个用例`
      const confirmed = window.confirm(
        `用图书借阅用例样例替换当前草稿？当前草稿有 ${summary}，替换后只能靠「导入 JSON」或重新编辑找回。`,
      )
      if (!confirmed) {
        setNotice({ title: copy.current.cancelledKeep, items: [] })
        return
      }
    }
    const sample = readUseCaseSample()
    setDiagramKind('usecase')
    setUcSpec(sample.spec)
    setUcReview(null)
    setUcPositionsById(undefined)
    setUcManualOpen(true)
    setUcResult(null)
    setError(null)
    lastGeneratedUcSpec.current = sample.spec
    const rendered = token ? await renderUseCaseDraft(sample.spec) : false
    const depCount = sample.spec.dependencies.length
    setNotice({
      title: rendered
        ? `已载入用例样例并出图：${sample.spec.actors.length} 个参与者、${sample.spec.useCases.length} 个用例`
        : `已载入用例样例：${sample.spec.actors.length} 个参与者、${sample.spec.useCases.length} 个用例、${sample.spec.links.length} 条关联${depCount ? `、${depCount} 条依赖` : ''}`,
      items: rendered
        ? sample.notices
        : [token ? '规格已就绪，点「重新排版」即可出图。' : '规格已写入，登录后即可出图。', ...sample.notices],
      action: token
        ? {
            label: copy.current.viewPreview,
            run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
          }
        : { label: copy.current.goLogin, run: onLogin },
    })
  }

  const handleLoadSample = async () => {
    if (isUseCase) await loadUseCaseSample()
    else await loadErSample()
  }

  const loadErSampleRef = useRef(loadErSample)
  loadErSampleRef.current = loadErSample
  const loadUseCaseSampleRef = useRef(loadUseCaseSample)
  loadUseCaseSampleRef.current = loadUseCaseSample

  // 欢迎页：聚焦描述框 / 载入 E-R 样例 / 载入用例样例
  useEffect(() => {
    if (!command) return
    if (command.type === 'sample') {
      void loadErSampleRef.current()
      return
    }
    if (command.type === 'usecase-sample') {
      void loadUseCaseSampleRef.current()
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
    const looksUseCase =
      isUseCase ||
      (typeof raw === 'object' &&
        raw !== null &&
        ((raw as { kind?: unknown }).kind === 'usecase' ||
          Array.isArray((raw as { useCases?: unknown }).useCases) ||
          Array.isArray((raw as { use_cases?: unknown }).use_cases)))

    if (looksUseCase) {
      const parsed = parseUseCaseSpec(raw)
      if (!parsed.ok) {
        setError({
          title: '导入没有完成',
          detail: parsed.error || '用例规格无法使用。',
          keptPreview: true,
        })
        return
      }
      setDiagramKind('usecase')
      setUcSpec(parsed.spec)
      setUcReview(null)
      setUcPositionsById(undefined)
      setUcManualOpen(true)
      setUcResult(null)
      setError(null)
      lastGeneratedUcSpec.current = parsed.spec
      const rendered = token ? await renderUseCaseDraft(parsed.spec) : false
      setNotice({
        title: rendered
          ? `已导入 ${file.name} 并出图：${parsed.spec.actors.length} 个参与者、${parsed.spec.useCases.length} 个用例`
          : `已导入 ${file.name}：${parsed.spec.actors.length} 个参与者、${parsed.spec.useCases.length} 个用例`,
        items: rendered
          ? parsed.notices
          : [
              token ? '规格已就绪，点「重新排版」即可出图。' : '规格已写入，登录后即可出图。',
              ...parsed.notices,
            ],
        action: token
          ? {
              label: copy.current.viewPreview,
              run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
            }
          : { label: copy.current.goLogin, run: onLogin },
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
    setDiagramKind('er')
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
            label: copy.current.viewPreview,
            run: () => document.getElementById('preview-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
          }
        : { label: copy.current.goLogin, run: onLogin },
    })
  }

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    // 清空 value，才能重复选择同一个文件
    event.target.value = ''
    if (file) void importFile(file)
  }

  const handleExport = () => {
    if (isUseCase) {
      const payload = toUseCaseJson(ucSpec)
      const name = `${safeFileName(ucSpec.title.trim() || ucSpec.system.trim() || 'usecase-spec')}.json`
      downloadText(name, `${JSON.stringify(payload, null, 2)}\n`)
      setNotice({
        title: copy.current.exported(name),
        items: [copy.current.exportedUc],
      })
      return
    }
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
    if (!activeResult) return
    const images = [activeResult.overview, ...activeResult.entities]
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
          title={t.homeTitle}
          data-testid="go-home"
        >
          <BrandMark />
          <div className="brand-text">
            <h1>{t.workbenchTitle}</h1>
            <p>{isUseCase ? t.workbenchSubUc : t.workbenchSubEr}</p>
          </div>
        </a>

        <DiagramKindSwitch
          value={diagramKind}
          onChange={changeDiagramKind}
          disabled={generating || loading}
        />

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
              {loading ? t.busyLayout : t.busyGenerate}
            </span>
          )}

          {!emptyDraft && (
            <button
              type="button"
              className={loading || generating ? 'btn btn-primary is-busy' : blocked ? 'btn' : 'btn btn-primary'}
              onClick={renderCurrent}
              disabled={loading || generating || blocked}
              title={blocked ? t.fixLeftFirst : t.submitLayout}
              data-testid="render"
              aria-busy={loading || generating}
            >
              {loading ? (
                <>
                  <span className="spinner spinner-sm" aria-hidden="true" />
                  {t.busyLayoutEllipsis}
                </>
              ) : generating ? (
                <>
                  <span className="spinner spinner-sm" aria-hidden="true" />
                  {t.busyGenerateEllipsis}
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
                ? t.channelOpenNamed(activeChannel.name, activeChannel.model || t.channelNoModel)
                : t.channelOpenTitle
            }
            data-testid="open-api-platform"
            data-provider={activeChannel?.preset || undefined}
          >
            {activeChannel ? (
              <ProviderIcon id={activeChannel.preset} size={15} className="wb-channel-logo" />
            ) : null}
            <span className="wb-channel-copy">
              <em>
                {activeChannel?.ready
                  ? t.channelReady
                  : activeChannel
                    ? t.channelWarn
                    : username
                      ? t.channelIdle
                      : t.apiPlatform}
              </em>
              <strong>
                {activeChannel ? activeChannel.name : username ? t.channelConnect : t.channelModels}
              </strong>
            </span>
          </button>
          <button type="button" className="btn btn-ghost" onClick={onUsage}>
            {t.tokenUsage}
          </button>
          {!username && (
            <button type="button" className="btn btn-primary" onClick={onLogin} data-testid="login-entry">
              {t.login}
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
                  {error.keptPreview && activeResult && (
                    <p className="banner-sub">{t.keptPreview}</p>
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
                      {t.goLogin}
                    </button>
                  )}
                </div>
                <button type="button" className="icon-btn" onClick={dismissError} aria-label={t.closeError}>
                  ×
                </button>
              </div>
            )}

            {!error && errors.length > 0 && (
              <div className="banner banner-warn" data-testid="validation-banner">
                <div className="banner-body">
                  <strong>
                    {isUseCase ? t.issuesLeft(errors.length) : t.issuesLeftEr(errors.length)}
                  </strong>
                  <ul className="banner-list">
                    {errors.slice(0, 6).map((issue, index) => (
                      <li key={index}>{issue.message}</li>
                    ))}
                  </ul>
                  {errors.length > 6 && <p className="banner-sub">{t.issuesMore(errors.length - 6)}</p>}
                </div>
              </div>
            )}

            {errors.length === 0 && warnings.length > 0 && (
              <div className="banner banner-muted">
                <div className="banner-body">
                  <strong>
                    {isUseCase ? t.warnOkUc(warnings.length) : t.warnOkEr(warnings.length)}
                  </strong>
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
                <button type="button" className="icon-btn" onClick={() => setNotice(null)} aria-label={t.closeNotice}>
                  ×
                </button>
              </div>
            )}
          </div>
        )}

        <div className="columns">
          <section className={`panel editor${emptyDraft && !activeManualOpen ? ' is-cold' : ''}`}>
            <div className="panel-head">
              <h2>{emptyDraft && !activeManualOpen ? t.panelStart : t.panelSpec}</h2>
              {!(emptyDraft && !activeManualOpen) && (
                <span className="muted">
                  {isUseCase
                    ? t.countUc(ucSpec.actors.length, ucSpec.useCases.length, ucSpec.links.length)
                    : t.countEr(spec.entities.length, spec.relations.length)}
                </span>
              )}
              <div className="panel-tools">
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => fileInput.current?.click()}
                  data-testid="import-json"
                >
                  {t.importJson}
                </button>
                {!(emptyDraft && !activeManualOpen) && (
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
                      {t.exportJson}
                    </button>
                    {!isUseCase && <SpecSearch spec={spec} onSelect={locateSpec} />}
                  </>
                )}
              </div>
            </div>

            <div className="panel-body">
              <DescribeBox
                text={isUseCase ? ucDescribe : describe}
                onTextChange={changeDescribe}
                onGenerate={() => void handleGenerate()}
                generating={generating}
                rendering={loading}
                replacing={!emptyDraft}
                ratio={ratio}
                onRatioChange={setRatio}
                error={isUseCase ? ucDescribeError : describeError}
                channelLabel={
                  isUseCase
                    ? null
                    : activeChannel?.ready
                      ? t.channelGenReady(activeChannel.name)
                      : activeChannel
                        ? t.channelGenWarn(activeChannel.name)
                        : null
                }
                onOpenChannel={onOpenApiPlatform}
                onLoadSample={() => void handleLoadSample()}
                sampleLabel={isUseCase ? t.sampleUc : t.sampleEr}
                loggedIn={loggedIn}
                onLogin={onLogin}
                diagramKind={diagramKind}
              />

              {isUseCase && ucReview && (
                <UseCaseReviewPanel
                  outcome={ucReview.outcome}
                  outdated={ucReview.draft !== ucSpec}
                  canReview={!!token && !generating && errors.length === 0}
                  onReview={() => {
                    if (!token) return
                    attachUseCaseReview(
                      ucReview.text,
                      ucSpec,
                      requestUseCaseReview(ucReview.text, ucSpec, token, copy.current.reviewUnavailable),
                    )
                  }}
                />
              )}

              {emptyDraft && !activeManualOpen ? (
                <div className="cold-manual">
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => (isUseCase ? setUcManualOpen(true) : setManualOpen(true))}
                    data-testid="open-manual-edit"
                  >
                    {isUseCase ? t.openManualUc : t.openManualEr}
                  </button>
                </div>
              ) : isUseCase ? (
                <div className="spec-band">
                  <label className="field spec-title-field">
                    <span className="field-label">{t.titleField}</span>
                    <input
                      className="input"
                      value={ucSpec.title}
                      placeholder={t.titlePhUc}
                      onChange={(event) => setUcSpec((current) => ({ ...current, title: event.target.value }))}
                      data-testid="uc-title-input"
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">{t.systemField}</span>
                    <input
                      className="input"
                      value={ucSpec.system}
                      placeholder={t.systemPh}
                      onChange={(event) => setUcSpec((current) => ({ ...current, system: event.target.value }))}
                      data-testid="uc-system-input"
                    />
                  </label>

                  <div className="section-head">
                    <h3>
                      {t.actors} <span className="count">{ucSpec.actors.length}</span>
                    </h3>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={addActor}
                      disabled={ucSpec.actors.length >= USECASE_LIMITS.actors}
                      data-testid="add-actor"
                    >
                      {t.addActor}
                    </button>
                  </div>
                  {ucSpec.actors.length === 0 ? (
                    <p className="hint spec-empty">{t.emptyActors}</p>
                  ) : (
                    <div className="card-list">
                      {ucSpec.actors.map((actor, index) => (
                        <ActorCard
                          key={actor.id}
                          actor={actor}
                          index={index}
                          locatedId={locatedId}
                          linkCount={ucSpec.links.filter((link) => link.actorId === actor.id).length}
                          onChange={replaceActor}
                          onRemove={() => removeActor(actor)}
                        />
                      ))}
                    </div>
                  )}

                  <div className="section-head">
                    <h3>
                      {t.useCases} <span className="count">{ucSpec.useCases.length}</span>
                    </h3>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={addUseCaseItem}
                      disabled={ucSpec.useCases.length >= USECASE_LIMITS.useCases}
                      data-testid="add-usecase"
                    >
                      {t.addUseCase}
                    </button>
                  </div>
                  {ucSpec.useCases.length === 0 ? (
                    <p className="hint spec-empty">{t.emptyUseCases}</p>
                  ) : (
                    <div className="card-list">
                      {ucSpec.useCases.map((item, index) => (
                        <UseCaseCard
                          key={item.id}
                          useCase={item}
                          index={index}
                          locatedId={locatedId}
                          linkCount={ucSpec.links.filter((link) => link.useCaseId === item.id).length}
                          onChange={replaceUseCase}
                          onRemove={() => removeUseCaseItem(item)}
                        />
                      ))}
                    </div>
                  )}

                  <div className="section-head">
                    <h3>
                      {t.links} <span className="count">{ucSpec.links.length}</span>
                    </h3>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={addUseCaseLinkItem}
                      disabled={
                        !ucSpec.actors.length ||
                        !ucSpec.useCases.length ||
                        ucSpec.links.length >= USECASE_LIMITS.links
                      }
                      title={
                        !ucSpec.actors.length || !ucSpec.useCases.length
                          ? t.needActorsAndUseCases
                          : undefined
                      }
                      data-testid="add-uclink"
                    >
                      {t.addLink}
                    </button>
                  </div>
                  {ucSpec.links.length === 0 ? (
                    <p className="hint spec-empty">{t.emptyLinks}</p>
                  ) : (
                    <div className="card-list">
                      {ucSpec.links.map((link, index) => (
                        <UseCaseLinkCard
                          key={link.id}
                          link={link}
                          index={index}
                          locatedId={locatedId}
                          actors={ucSpec.actors}
                          useCases={ucSpec.useCases}
                          onChange={replaceUseCaseLink}
                          onRemove={() => removeUseCaseLinkItem(link)}
                        />
                      ))}
                    </div>
                  )}

                  <div className="section-head">
                    <h3>
                      {t.deps} <span className="count">{ucSpec.dependencies.length}</span>
                    </h3>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={addUseCaseDepItem}
                      disabled={
                        ucSpec.useCases.length < 2 ||
                        ucSpec.dependencies.length >= USECASE_LIMITS.dependencies
                      }
                      title={ucSpec.useCases.length < 2 ? t.needTwoUseCases : undefined}
                      data-testid="add-ucdep"
                    >
                      {t.addDep}
                    </button>
                  </div>
                  {ucSpec.dependencies.length === 0 ? (
                    <p className="hint spec-empty">{t.emptyDeps}</p>
                  ) : (
                    <div className="card-list">
                      {ucSpec.dependencies.map((dep, index) => (
                        <UseCaseDepCard
                          key={dep.id}
                          dep={dep}
                          index={index}
                          locatedId={locatedId}
                          useCases={ucSpec.useCases}
                          onChange={replaceUseCaseDep}
                          onRemove={() => removeUseCaseDepItem(dep)}
                        />
                      ))}
                    </div>
                  )}

                  <p className="foot-note">
                    {t.ucLimits(
                      USECASE_LIMITS.actors,
                      USECASE_LIMITS.useCases,
                      USECASE_LIMITS.links,
                      USECASE_LIMITS.dependencies,
                      USECASE_LIMITS.label,
                    )}
                  </p>
                </div>
              ) : (
                <>
                  <div className="spec-band">
                    <label className="field spec-title-field">
                      <span className="field-label">{t.titleField}</span>
                      <input
                        className="input"
                        value={spec.title}
                        placeholder={t.titlePhEr}
                        onChange={(event) => setSpec((current) => ({ ...current, title: event.target.value }))}
                        data-testid="title-input"
                      />
                    </label>

                    <div className="section-head">
                      <h3>
                        {t.entities} <span className="count">{spec.entities.length}</span>
                      </h3>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={addEntity}
                        disabled={spec.entities.length >= LIMITS.entities}
                        data-testid="add-entity"
                      >
                        {t.addEntity}
                      </button>
                    </div>

                    {spec.entities.length === 0 ? (
                      <p className="hint spec-empty">{t.emptyEntities}</p>
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
                        {t.relations} <span className="count">{spec.relations.length}</span>
                      </h3>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={addRelation}
                        disabled={spec.entities.length < 2 || spec.relations.length >= LIMITS.relations}
                        title={spec.entities.length < 2 ? t.needTwoEntities : undefined}
                        data-testid="add-relation"
                      >
                        {t.addRelation}
                      </button>
                    </div>

                    {spec.relations.length === 0 ? (
                      <p className="hint spec-empty">
                        {spec.entities.length < 2 ? t.emptyRelationsNeedEntities : t.emptyRelations}
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
                      {t.erLimits(LIMITS.entities, LIMITS.relations, LIMITS.attrs, LIMITS.label)}
                    </p>
                  </div>
                </>
              )}
            </div>
          </section>

          <PreviewPanel
            result={activeResult}
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
            hasSavedLayout={!!activeSavedPositions}
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
            sampleLabel={isUseCase ? t.loadSampleUc : t.loadSampleEr}
            loggedIn={loggedIn}
            onLogin={onLogin}
            diagramKind={diagramKind}
            backendPending={false}
          />
        </div>
      </main>

    </div>
  )
}

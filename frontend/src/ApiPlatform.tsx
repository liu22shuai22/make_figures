import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import BrandMark from './components/BrandMark'
import ProviderIcon from './components/ProviderIcon'
import ThemeToggle from './components/ThemeToggle'
import type { Theme } from './theme'
import { downloadText, safeFileName } from './download'
import {
  activateProvider,
  exportProviders,
  fetchProviders,
  importProviders,
  listRemoteModels,
  probeGateway,
  removeProvider,
  saveProvider,
  type ModelOption,
  type ProviderPreset,
  type ProviderPublic,
  type ProvidersPayload,
} from './providersApi'

interface Props {
  onBack: () => void
  onLogin: () => void
  theme: Theme
  onToggleTheme: () => void
  token: string | null
}

const EMPTY_FORM = {
  id: '',
  name: '',
  kind: 'openai' as 'openai' | 'anthropic',
  base_url: '',
  api_key: '',
  model: '',
  preset: 'newapi',
}

type RailScope = 'all' | 'local' | 'cn' | 'intl'

/** 按「本机 / 国内 / 国际」分轨，对应 E-R 分区接线 */
const RAIL_GROUPS: { id: Exclude<RailScope, 'all'>; label: string; ids: readonly string[] }[] = [
  { id: 'local', label: '本机', ids: ['newapi', 'ollama', 'magpie'] },
  {
    id: 'cn',
    label: '国内',
    ids: [
      'siliconflow',
      'deepseek',
      'moonshot',
      'dashscope',
      'xiaomi',
      'hunyuan',
      'zhipu',
      'doubao',
      'qianfan',
      'minimax',
      'stepfun',
      'baichuan',
      'yi',
      'spark',
      'sensenova',
      'modelscope',
    ],
  },
  {
    id: 'intl',
    label: '国际',
    ids: [
      'openai',
      'anthropic',
      'gemini',
      'openrouter',
      'groq',
      'mistral',
      'xai',
      'together',
      'fireworks',
    ],
  },
]

const QUICK_PRESET_IDS = RAIL_GROUPS.flatMap((group) => group.ids)

const RAIL_SCOPE_TABS: { id: RailScope; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'local', label: '本机' },
  { id: 'cn', label: '国内' },
  { id: 'intl', label: '国际' },
]

function hostOf(url: string) {
  try {
    return new URL(url).host || url
  } catch {
    return url || '未填地址'
  }
}

function formFromPreset(preset: ProviderPreset) {
  return {
    id: '',
    name: preset.name,
    kind: preset.kind,
    base_url: preset.base_url,
    api_key: preset.default_key,
    model: preset.model,
    preset: preset.id,
  }
}

/** 各渠道品牌微色：只作接线高亮，不改整页主题 */
function providerTone(id?: string | null) {
  switch ((id || '').toLowerCase()) {
    case 'newapi':
      return 'newapi'
    case 'siliconflow':
      return 'siliconflow'
    case 'deepseek':
      return 'deepseek'
    case 'openai':
      return 'openai'
    case 'anthropic':
      return 'anthropic'
    case 'gemini':
      return 'gemini'
    case 'openrouter':
      return 'openrouter'
    case 'moonshot':
      return 'moonshot'
    case 'dashscope':
      return 'dashscope'
    case 'xiaomi':
      return 'xiaomi'
    case 'hunyuan':
      return 'hunyuan'
    case 'zhipu':
      return 'zhipu'
    case 'doubao':
      return 'doubao'
    case 'qianfan':
    case 'baidu':
      return 'qianfan'
    case 'minimax':
      return 'minimax'
    case 'stepfun':
      return 'stepfun'
    case 'baichuan':
      return 'baichuan'
    case 'yi':
      return 'yi'
    case 'spark':
      return 'spark'
    case 'sensenova':
      return 'sensenova'
    case 'modelscope':
      return 'modelscope'
    case 'groq':
      return 'groq'
    case 'mistral':
      return 'mistral'
    case 'xai':
      return 'xai'
    case 'together':
      return 'together'
    case 'fireworks':
      return 'fireworks'
    case 'ollama':
      return 'ollama'
    case 'magpie':
      return 'magpie'
    default:
      return 'custom'
  }
}

export default function ApiPlatform({ onBack, onLogin, theme, onToggleTheme, token }: Props) {
  const [payload, setPayload] = useState<ProvidersPayload>()
  const [form, setForm] = useState(EMPTY_FORM)
  const [models, setModels] = useState<ModelOption[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [guideOpen, setGuideOpen] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const [wireFlash, setWireFlash] = useState(false)
  const [probing, setProbing] = useState(false)
  const [railQuery, setRailQuery] = useState('')
  const [railScope, setRailScope] = useState<RailScope>('all')
  const [addOpen, setAddOpen] = useState(false)
  const [bridge, setBridge] = useState<{ d: string; w: number; h: number } | null>(null)
  const [probeEcho, setProbeEcho] = useState<{
    ok: boolean
    models: number
    detail: string
  } | null>(null)
  const flashTimer = useRef<ReturnType<typeof window.setTimeout>>()
  const echoTimer = useRef<ReturnType<typeof window.setTimeout>>()
  const boardRef = useRef<HTMLDivElement>(null)
  const dockRef = useRef<HTMLSpanElement>(null)
  const importInput = useRef<HTMLInputElement>(null)

  const providers = payload?.providers || []

  const active = useMemo(
    () => payload?.providers.find((item) => item.id === payload.active_id) || null,
    [payload],
  )

  const tone = providerTone(active?.preset || form.preset)

  const sparkWire = () => {
    window.clearTimeout(flashTimer.current)
    setWireFlash(true)
    flashTimer.current = window.setTimeout(() => setWireFlash(false), 560)
  }

  const showProbeEcho = (echo: { ok: boolean; models: number; detail: string }) => {
    window.clearTimeout(echoTimer.current)
    setProbeEcho(echo)
    echoTimer.current = window.setTimeout(() => setProbeEcho(null), echo.ok ? 5200 : 6400)
    if (echo.ok) sparkWire()
  }

  useEffect(
    () => () => {
      window.clearTimeout(flashTimer.current)
      window.clearTimeout(echoTimer.current)
    },
    [],
  )

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 4200)
    return () => window.clearTimeout(timer)
  }, [notice])

  const clearProbeEcho = () => {
    window.clearTimeout(echoTimer.current)
    setProbeEcho(null)
  }

  const selectedPreset = useMemo(
    () => (payload?.presets || []).find((item) => item.id === form.preset) || null,
    [payload, form.preset],
  )

  const readySteps = useMemo(
    () => ({
      url: Boolean(form.base_url.trim()),
      key: Boolean(form.api_key.trim()),
      model: Boolean(form.model.trim()),
    }),
    [form.api_key, form.base_url, form.model],
  )
  const readyCount = Number(readySteps.url) + Number(readySteps.key) + Number(readySteps.model)
  const formReady = readyCount === 3

  const quickPresets = useMemo(() => {
    const all = payload?.presets || []
    return QUICK_PRESET_IDS.map((id) => all.find((item) => item.id === id)).filter(
      (item): item is ProviderPreset => Boolean(item),
    )
  }, [payload])

  const railGroups = useMemo(() => {
    const q = railQuery.trim().toLowerCase()
    return RAIL_GROUPS.map((group) => {
      const items = group.ids
        .map((id) => quickPresets.find((item) => item.id === id))
        .filter((item): item is ProviderPreset => Boolean(item))
        .filter((item) => {
          if (!q) return true
          return (
            item.name.toLowerCase().includes(q) ||
            item.id.toLowerCase().includes(q) ||
            hostOf(item.base_url).toLowerCase().includes(q)
          )
        })
      return { ...group, items }
    }).filter((group) => {
      if (railScope !== 'all' && group.id !== railScope) return false
      return group.items.length > 0
    })
  }, [quickPresets, railQuery, railScope])

  const railVisibleCount = useMemo(
    () => railGroups.reduce((sum, group) => sum + group.items.length, 0),
    [railGroups],
  )

  const scopeCounts = useMemo(() => {
    const counts: Record<RailScope, number> = {
      all: quickPresets.length,
      local: 0,
      cn: 0,
      intl: 0,
    }
    for (const group of RAIL_GROUPS) {
      counts[group.id] = group.ids.filter((id) => quickPresets.some((item) => item.id === id)).length
    }
    return counts
  }, [quickPresets])

  const selectedRailScope = useMemo(() => {
    for (const group of RAIL_GROUPS) {
      if (group.ids.includes(form.preset)) return group
    }
    return null
  }, [form.preset])

  const savedRail = useMemo(() => {
    const q = railQuery.trim().toLowerCase()
    return providers.filter((item) => {
      if (!q) return true
      return (
        item.name.toLowerCase().includes(q) ||
        hostOf(item.base_url).toLowerCase().includes(q) ||
        (item.model || '').toLowerCase().includes(q) ||
        item.preset.toLowerCase().includes(q)
      )
    })
  }, [providers, railQuery])

  const selectionHidden =
    Boolean(form.preset) &&
    (providers.length === 0 || addOpen) &&
    !railGroups.some((group) => group.items.some((item) => item.id === form.preset))

  const updateBridge = useCallback(() => {
    const board = boardRef.current
    const dock = dockRef.current
    const joint = board?.querySelector('.api-rail li.is-on .api-rail-joint') as HTMLElement | null
    if (!board || !dock || !joint) {
      board?.classList.remove('is-stacked')
      setBridge(null)
      return
    }
    const br = board.getBoundingClientRect()
    const jr = joint.getBoundingClientRect()
    const dr = dock.getBoundingClientRect()
    if (jr.width < 1 || dr.width < 1) {
      board.classList.remove('is-stacked')
      setBridge(null)
      return
    }
    const x1 = jr.left + jr.width / 2 - br.left
    const y1 = jr.top + jr.height / 2 - br.top
    const x2 = dr.left + dr.width / 2 - br.left
    const y2 = dr.top + dr.height / 2 - br.top
    const stacked =
      getComputedStyle(board).gridTemplateColumns.trim().split(/\s+/).length < 2 ||
      (y2 - y1 > 48 && Math.abs(x2 - x1) < Math.max(72, br.width * 0.28))
    board.classList.toggle('is-stacked', stacked)
    let d: string
    if (stacked) {
      const dy = Math.max(40, (y2 - y1) * 0.38)
      d = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${x1.toFixed(1)} ${(y1 + dy).toFixed(1)}, ${x2.toFixed(
        1,
      )} ${(y2 - dy).toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`
    } else {
      const dx = Math.max(48, (x2 - x1) * 0.42)
      d = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + dx).toFixed(1)} ${y1.toFixed(1)}, ${(
        x2 - dx
      ).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`
    }
    setBridge({ d, w: br.width, h: br.height })
  }, [])

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => updateBridge())
    const board = boardRef.current
    const channels = board?.querySelector('.api-channels')
    const onScroll = () => updateBridge()
    channels?.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    const observer = board ? new ResizeObserver(onScroll) : null
    if (board && observer) observer.observe(board)
    return () => {
      window.cancelAnimationFrame(frame)
      channels?.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      observer?.disconnect()
    }
  }, [
    updateBridge,
    form.preset,
    form.id,
    railScope,
    railQuery,
    wireFlash,
    railVisibleCount,
    providers,
    addOpen,
    savedRail.length,
  ])

  useEffect(() => {
    const node = boardRef.current?.querySelector('.api-rail li.is-on') as HTMLElement | null
    if (!node) return
    const frame = window.requestAnimationFrame(() => {
      node.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      updateBridge()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [form.preset, form.id, railScope, railQuery, providers.length, addOpen, updateBridge])

  const revealSelection = () => {
    setRailQuery('')
    setRailScope(selectedRailScope?.id || 'all')
  }

  const load = async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      setPayload(await fetchProviders(token))
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取失败')
    } finally {
      setLoading(false)
    }
  }

  const onExport = async () => {
    if (!token) return
    const withSecrets =
      providers.length > 0 &&
      window.confirm('是否一并导出明文 API Key？\n选「取消」则只导出模板（不含密钥，适合课堂发放）。')
    setBusy(true)
    setError(null)
    try {
      const bundle = await exportProviders(token, withSecrets)
      const stamp = new Date().toISOString().slice(0, 10)
      const suffix = withSecrets ? 'secrets' : 'template'
      downloadText(
        safeFileName(`erflow-providers-${suffix}-${stamp}.json`),
        `${JSON.stringify(bundle, null, 2)}\n`,
      )
      setNotice(
        withSecrets
          ? `已导出 ${bundle.providers.length} 条渠道（含密钥，请妥善保管）。`
          : `已导出 ${bundle.providers.length} 条渠道模板（不含密钥）。`,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : '导出失败')
    } finally {
      setBusy(false)
    }
  }

  const onImportFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !token) return
    setBusy(true)
    setError(null)
    try {
      const text = await file.text()
      let bundle: Record<string, unknown>
      try {
        bundle = JSON.parse(text) as Record<string, unknown>
      } catch {
        throw new Error('不是有效的 JSON 文件')
      }
      const mode: 'merge' | 'replace' =
        providers.length === 0
          ? 'replace'
          : window.confirm('合并到现有渠道？\n确定 = 合并（同 id 覆盖）\n取消 = 整表替换')
            ? 'merge'
            : 'replace'
      const next = await importProviders(token, bundle, mode)
      setPayload(next)
      setModels([])
      clearProbeEcho()
      setNotice(`已${mode === 'merge' ? '合并' : '替换'}导入 ${next.providers.length} 条渠道。`)
      sparkWire()
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入失败')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    void load()
  }, [token])

  useEffect(() => {
    if (!payload?.presets?.length) return
    setForm((current) => {
      if (current.id || current.name || current.base_url) return current
      const preset = payload.presets.find((item) => item.id === 'newapi') || payload.presets[0]
      return formFromPreset(preset)
    })
  }, [payload])

  const applyPreset = (preset: ProviderPreset) => {
    setForm(formFromPreset(preset))
    setModels([])
    setNotice(null)
    setError(null)
    setShowKey(false)
    clearProbeEcho()
    if (providers.length) setAddOpen(true)
    sparkWire()
  }

  const onPresetChange = (presetId: string) => {
    const preset = (payload?.presets || []).find((item) => item.id === presetId)
    if (preset) applyPreset(preset)
    else setForm((current) => ({ ...current, preset: presetId }))
  }

  const editProvider = (item: ProviderPublic) => {
    setForm({
      id: item.id,
      name: item.name,
      kind: item.kind,
      base_url: item.base_url,
      api_key: item.api_key_masked,
      model: item.model,
      preset: item.preset,
    })
    setModels([])
    setNotice(null)
    setError(null)
    setShowKey(false)
    setAddOpen(false)
    clearProbeEcho()
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      const next = await saveProvider(token, {
        id: form.id || undefined,
        name: form.name.trim() || '未命名渠道',
        kind: form.kind,
        base_url: form.base_url.trim(),
        api_key: form.api_key,
        model: form.model.trim(),
        preset: form.preset,
        activate: true,
      })
      setPayload(next)
      setNotice('已保存并接通。')
      sparkWire()
      const preset = next.presets.find((item) => item.id === 'newapi') || next.presets[0]
      setForm(preset ? formFromPreset(preset) : EMPTY_FORM)
      setModels([])
      setShowKey(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  const onActivate = async (id: string) => {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      setPayload(await activateProvider(token, id))
      setNotice('已接通此渠道。')
      sparkWire()
    } catch (err) {
      setError(err instanceof Error ? err.message : '切换失败')
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (id: string) => {
    if (!token) return
    if (!window.confirm('确定删除这个渠道？')) return
    setBusy(true)
    setError(null)
    try {
      const next = await removeProvider(token, id)
      setPayload(next)
      if (form.id === id) {
        const preset = next.presets.find((item) => item.id === 'newapi') || next.presets[0]
        setForm(preset ? formFromPreset(preset) : EMPTY_FORM)
      }
      setNotice('已删除。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    } finally {
      setBusy(false)
    }
  }

  const onProbeGateway = async () => {
    if (!token) return
    setBusy(true)
    setProbing(true)
    setError(null)
    setNotice(null)
    window.clearTimeout(echoTimer.current)
    setProbeEcho(null)
    try {
      const result = await probeGateway(token, form.base_url || undefined, form.api_key || undefined)
      setModels(result.models)
      setForm((current) => ({
        ...current,
        preset: current.preset === 'custom' || !current.preset ? 'newapi' : current.preset,
        name: current.name || 'New API 网关',
        kind: 'openai',
        base_url: result.base_url,
      }))
      if (!result.ok) {
        const detail = result.error || '网关未连通'
        setError(detail)
        showProbeEcho({ ok: false, models: 0, detail })
      } else if (result.error) {
        setNotice(result.error)
        showProbeEcho({
          ok: true,
          models: result.models.length,
          detail: result.error,
        })
      } else {
        const detail =
          result.models.length > 0
            ? `发现 ${result.models.length} 个模型`
            : '已连通，未返回模型列表'
        setNotice(detail)
        showProbeEcho({ ok: true, models: result.models.length, detail })
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : '探测网关失败'
      setError(detail)
      showProbeEcho({ ok: false, models: 0, detail })
    } finally {
      setBusy(false)
      setProbing(false)
    }
  }

  const onListModels = async () => {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      const listed = await listRemoteModels(token, {
        base_url: form.base_url,
        api_key: form.api_key,
        id: form.id || undefined,
      })
      setModels(listed)
      setNotice(listed.length ? `拉到 ${listed.length} 个模型。` : '接口没有返回模型。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '拉取模型失败')
    } finally {
      setBusy(false)
    }
  }

  const resetForm = () => {
    const preset = payload?.presets.find((item) => item.id === 'newapi') || payload?.presets[0]
    setForm(preset ? formFromPreset(preset) : EMPTY_FORM)
    setModels([])
    setNotice(null)
    setError(null)
    setShowKey(false)
    clearProbeEcho()
    if (providers.length) setAddOpen(true)
  }

  const hopKicker = probing
    ? '探测中'
    : probeEcho
      ? probeEcho.ok
        ? '探测通'
        : '探测断'
      : formReady
        ? '可接通'
        : '接驳中'

  const hopSteps = probing
    ? '…'
    : probeEcho
      ? probeEcho.ok
        ? String(probeEcho.models)
        : '!'
      : `${readyCount}/3`

  const statusClass = active?.ready ? ' is-ready' : active ? ' is-warn' : ' is-idle'

  return (
    <div className="app">
      <header className="topbar usage-topbar">
        <div className="brand">
          <BrandMark />
          <div className="brand-text">
            <h1>API 平台</h1>
          </div>
        </div>
        <div className="toolbar">
          <button type="button" className="btn" onClick={onBack}>
            返回工作台
          </button>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </header>

      <main className="api-platform" aria-busy={loading || busy} data-provider={tone}>
        <div className="api-bar">
          <p className="api-scope">把模型渠道接进 ERFlow——像连上一条联系。</p>
          <div className="api-bar-actions">
            <button
              type="button"
              className="api-text-btn"
              onClick={() => setGuideOpen((open) => !open)}
              aria-expanded={guideOpen}
            >
              {guideOpen ? '收起说明' : '接入说明'}
            </button>
            {token && (
              <>
                <button
                  type="button"
                  className="api-text-btn"
                  disabled={loading || busy}
                  onClick={() => void load()}
                >
                  {loading ? '读取中…' : '刷新'}
                </button>
                <button
                  type="button"
                  className="api-text-btn"
                  disabled={loading || busy || providers.length === 0}
                  onClick={() => void onExport()}
                >
                  导出
                </button>
                <button
                  type="button"
                  className="api-text-btn"
                  disabled={loading || busy}
                  onClick={() => importInput.current?.click()}
                >
                  导入
                </button>
                <input
                  ref={importInput}
                  type="file"
                  accept="application/json,.json"
                  hidden
                  onChange={(event) => void onImportFile(event)}
                />
              </>
            )}
          </div>
        </div>

        {guideOpen && (
          <div className="api-guide">
            <p>
              推荐{' '}
              <a href="https://github.com/QuantumNous/new-api" target="_blank" rel="noreferrer">
                New API
              </a>
              ：本机 <code>127.0.0.1:3000</code> 起服务，控制台建渠道与令牌后填入本页。也可直连硅基流动、DeepSeek
              等官方接口。渠道可「导出」成 JSON 备份或课堂模板，「导入」时选择合并或整表替换。
            </p>
          </div>
        )}

        {!token && (
          <div className="api-gate" role="status">
            <div>
              <strong>登录后管理渠道</strong>
              <p>密钥只保存在本机，不会上传。</p>
            </div>
            <button type="button" className="btn btn-primary" onClick={onLogin}>
              去登录
            </button>
          </div>
        )}

        {token && (
          <>
            {(error || notice) && (
              <p className={'api-flash ' + (error ? 'is-error' : 'is-info')} role="status">
                {error || notice}
                <button type="button" className="api-flash-close" onClick={() => { setError(null); setNotice(null) }} aria-label="关闭">
                  ×
                </button>
              </p>
            )}

            <section
              className={
                'api-shell' +
                (wireFlash ? ' is-flash' : '') +
                (probing ? ' is-probing' : '')
              }
              data-provider={tone}
            >
              <div className={'api-status' + statusClass} aria-label="当前启用渠道">
                <span className="api-status-badge" aria-hidden="true">
                  <ProviderIcon
                    id={active?.preset || form.preset || 'newapi'}
                    size={22}
                    className="api-status-logo"
                  />
                  <i className="api-status-pulse" />
                </span>
                <div className="api-status-copy">
                  {active ? (
                    <>
                      <p className="api-status-kicker">{active.ready ? '已接通' : '接线未完成'}</p>
                      <p className="api-status-title">
                        <strong>{active.name}</strong>
                        <span>{active.model || '未选模型'}</span>
                      </p>
                      <p className="api-status-sub">
                        {hostOf(active.base_url)}
                        <span aria-hidden="true">·</span>
                        <em className={active.ready ? 'is-ok' : 'is-bad'}>
                          {active.ready ? '生成将走此渠道' : '补全 Key 与模型'}
                        </em>
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="api-status-kicker">{readyCount ? '配置中' : '待接线'}</p>
                      <p className="api-status-title">
                        <strong>{form.name || '选左侧节点'}</strong>
                        {readyCount > 0 && <span>{readyCount}/3 已填</span>}
                      </p>
                      <p className="api-status-sub">
                        {readySteps.url ? hostOf(form.base_url) : '选节点 → 填 Key → 选模型'}
                        {readyCount > 0 && !formReady && (
                          <>
                            <span aria-hidden="true">·</span>
                            <em className="is-bad">
                              {!readySteps.key ? '缺 Key' : !readySteps.model ? '缺模型' : '继续补全'}
                            </em>
                          </>
                        )}
                      </p>
                    </>
                  )}
                </div>
                <div className="api-status-flow" aria-hidden="true">
                  <span className={'api-flow-node is-src' + (readySteps.url || active ? ' is-lit' : '')} />
                  <span className="api-flow-wire">
                    <i />
                  </span>
                  <span className={'api-flow-diamond' + (readySteps.key || active?.ready ? ' is-lit' : '')} />
                  <span className="api-flow-wire">
                    <i />
                  </span>
                  <span
                    className={
                      'api-flow-node is-dst' + (formReady || active?.ready ? ' is-lit' : '')
                    }
                  />
                </div>
                {active && (
                  <button
                    type="button"
                    className="api-status-edit"
                    disabled={busy}
                    onClick={() => editProvider(active)}
                  >
                    编辑
                  </button>
                )}
              </div>

              <div
                className={
                  'api-board' +
                  (bridge ? ' is-bridging' : '') +
                  (wireFlash ? ' is-spark' : '') +
                  (probing ? ' is-probing' : '') +
                  (probeEcho?.ok ? ' is-probe-ok' : '') +
                  (probeEcho && !probeEcho.ok ? ' is-probe-fail' : '') +
                  (formReady ? ' is-form-ready' : '')
                }
                ref={boardRef}
              >
                {bridge && (
                  <svg
                    className="api-bridge"
                    width={bridge.w}
                    height={bridge.h}
                    viewBox={`0 0 ${bridge.w} ${bridge.h}`}
                    aria-hidden="true"
                  >
                    <path className="api-bridge-glow" d={bridge.d} />
                    <path className="api-bridge-path" d={bridge.d} />
                    <circle className="api-bridge-pulse" r="3.5">
                      <animateMotion
                        dur={probing ? '0.7s' : probeEcho && !probeEcho.ok ? '2.2s' : '1.4s'}
                        repeatCount="indefinite"
                        path={bridge.d}
                      />
                    </circle>
                  </svg>
                )}

                <aside className="api-channels" aria-label="已保存渠道">
                  <header className="api-panel-head">
                    <h3>{providers.length ? '渠道节点' : '快捷节点'}</h3>
                    <span>{providers.length ? providers.length : railVisibleCount}</span>
                  </header>

                  {loading && <p className="api-empty">读取中…</p>}

                  {!loading && providers.length > 0 && (
                    <div
                      className={
                        'api-rail api-rail-saved' + (savedRail.length > 1 ? ' is-multi' : '')
                      }
                    >
                      <div className="api-rail-tools">
                        <input
                          className="input api-rail-search"
                          value={railQuery}
                          onChange={(event) => setRailQuery(event.target.value)}
                          placeholder="搜已保存渠道"
                          aria-label="搜索已保存渠道"
                        />
                      </div>

                      {savedRail.length === 0 ? (
                        <p className="api-empty">没有匹配的已保存渠道。</p>
                      ) : (
                        <ul>
                          {savedRail.map((item, index) => {
                            const isActive = item.id === payload?.active_id
                            const isEditing = Boolean(form.id) && form.id === item.id
                            const on = form.id ? isEditing : isActive
                            const dim = savedRail.length > 1 && !on
                            return (
                              <li
                                key={item.id}
                                style={{ ['--i' as string]: index }}
                                data-provider={providerTone(item.preset)}
                                className={
                                  (on ? 'is-on' : '') +
                                  (isActive ? ' is-live' : '') +
                                  (!item.ready ? ' is-warn' : '') +
                                  (dim ? ' is-dim' : '')
                                }
                              >
                                <span className="api-rail-joint" aria-hidden="true" />
                                <button
                                  type="button"
                                  className={on ? 'is-on' : undefined}
                                  disabled={busy}
                                  onClick={() => {
                                    editProvider(item)
                                    sparkWire()
                                  }}
                                >
                                  <ProviderIcon id={item.preset} size={18} className="api-quick-logo" />
                                  <span className="api-quick-text">
                                    <strong>{item.name}</strong>
                                    <span>
                                      {item.model || '未填模型'}
                                      <i aria-hidden="true"> · </i>
                                      {hostOf(item.base_url)}
                                    </span>
                                  </span>
                                  {isActive ? (
                                    <em className="api-rail-lead">已接通</em>
                                  ) : isEditing ? (
                                    <em className="api-rail-lead">接线中</em>
                                  ) : !item.ready ? (
                                    <em className="api-rail-lead is-warn">未就绪</em>
                                  ) : null}
                                </button>
                                <div className="api-rail-ops">
                                  {!isActive && (
                                    <button
                                      type="button"
                                      className="api-mini"
                                      disabled={busy}
                                      onClick={() => void onActivate(item.id)}
                                    >
                                      接通
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    className="api-mini is-danger"
                                    disabled={busy}
                                    onClick={() => void onDelete(item.id)}
                                  >
                                    删
                                  </button>
                                </div>
                              </li>
                            )
                          })}
                        </ul>
                      )}

                      <button
                        type="button"
                        className={'api-rail-add-toggle' + (addOpen ? ' is-open' : '')}
                        onClick={() => setAddOpen((open) => !open)}
                        aria-expanded={addOpen}
                      >
                        {addOpen ? '收起新节点' : '加新节点'}
                      </button>
                    </div>
                  )}

                  {!loading && (providers.length === 0 || addOpen) && (
                    <div className={'api-rail' + (providers.length ? ' api-rail-presets' : '')}>
                      {providers.length > 0 && (
                        <p className="api-rail-group-label api-rail-presets-label">
                          从预设拉线
                          <span>{railVisibleCount}</span>
                        </p>
                      )}
                      <div className="api-rail-tools">
                        <input
                          className="input api-rail-search"
                          value={railQuery}
                          onChange={(event) => setRailQuery(event.target.value)}
                          placeholder="搜渠道 / 域名"
                          aria-label="搜索渠道"
                        />
                        <div className="api-rail-scopes" role="tablist" aria-label="分区">
                          {RAIL_SCOPE_TABS.map((tab) => (
                            <button
                              key={tab.id}
                              type="button"
                              role="tab"
                              aria-selected={railScope === tab.id}
                              className={railScope === tab.id ? 'is-on' : undefined}
                              onClick={() => setRailScope(tab.id)}
                            >
                              {tab.label}
                              <small>{scopeCounts[tab.id]}</small>
                            </button>
                          ))}
                        </div>
                      </div>

                      {selectionHidden && (
                        <button type="button" className="api-rail-recall" onClick={revealSelection}>
                          当前接线在「{selectedRailScope?.label || '全部'}」
                          <span>回到节点</span>
                        </button>
                      )}

                      {railGroups.length === 0 && !selectionHidden && (
                        <p className="api-empty">没有匹配的节点，换个关键词试试。</p>
                      )}

                      {railGroups.map((group) => (
                        <div key={group.id} className="api-rail-group" data-scope={group.id}>
                          <p className="api-rail-group-label">
                            {group.label}
                            <span>{group.items.length}</span>
                          </p>
                          <ul>
                            {group.items.map((preset, index) => {
                              const on = !form.id && form.preset === preset.id
                              return (
                                <li
                                  key={preset.id}
                                  style={{ ['--i' as string]: index }}
                                  data-provider={providerTone(preset.id)}
                                  className={on ? 'is-on' : undefined}
                                >
                                  <span className="api-rail-joint" aria-hidden="true" />
                                  <button
                                    type="button"
                                    className={on ? 'is-on' : undefined}
                                    disabled={busy}
                                    onClick={() => applyPreset(preset)}
                                  >
                                    <ProviderIcon id={preset.id} size={18} className="api-quick-logo" />
                                    <span className="api-quick-text">
                                      <strong>{preset.name}</strong>
                                      <span>{hostOf(preset.base_url) || '自定义地址'}</span>
                                    </span>
                                    {on && <em className="api-rail-lead">接线中</em>}
                                  </button>
                                </li>
                              )
                            })}
                          </ul>
                        </div>
                      ))}
                    </div>
                  )}
                </aside>

                <div className={'api-editor' + (wireFlash ? ' is-wired' : '')} data-provider={tone}>
                  <span className="api-wire-dock" ref={dockRef} aria-hidden="true" />
                  <header className="api-panel-head">
                    <h3>{form.id ? '调整接线' : '拉线配置'}</h3>
                    {form.id && (
                      <button type="button" className="api-text-btn" disabled={busy} onClick={resetForm}>
                        新建
                      </button>
                    )}
                  </header>

                  <div
                    className={
                      'api-hop' +
                      (formReady && !probeEcho && !probing ? ' is-ready' : '') +
                      (probing ? ' is-probing' : '') +
                      (probeEcho?.ok ? ' is-echo-ok' : '') +
                      (probeEcho && !probeEcho.ok ? ' is-echo-fail' : '')
                    }
                    aria-live="polite"
                  >
                    <ProviderIcon id={form.preset || 'newapi'} size={16} className="api-hop-logo" />
                    <div className="api-hop-copy">
                      <span className="api-hop-kicker">{hopKicker}</span>
                      <strong>{form.name || selectedPreset?.name || '未选节点'}</strong>
                    </div>
                    <em className="api-hop-host">
                      {probeEcho
                        ? probeEcho.detail
                        : readySteps.url
                          ? hostOf(form.base_url)
                          : '等待地址'}
                    </em>
                    <span className="api-hop-steps" title={probeEcho ? probeEcho.detail : undefined}>
                      {hopSteps}
                      {probeEcho?.ok ? <small>模</small> : null}
                    </span>
                  </div>

                  <form className="api-form" onSubmit={onSubmit}>
                    <label className="api-field api-field-full">
                      <span>预设</span>
                      <div className="api-preset-select">
                        <ProviderIcon id={form.preset} size={18} className="api-preset-logo" />
                        <select
                          className="input"
                          value={form.preset}
                          onChange={(event) => onPresetChange(event.target.value)}
                          disabled={busy}
                          title={selectedPreset?.hint || undefined}
                        >
                          {(payload?.presets || []).map((preset) => (
                            <option key={preset.id} value={preset.id}>
                              {preset.name}
                            </option>
                          ))}
                        </select>
                      </div>
                    </label>

                    <label className="api-field">
                      <span>名称</span>
                      <input
                        className="input"
                        value={form.name}
                        onChange={(event) => setForm({ ...form, name: event.target.value })}
                        placeholder="例如 New API"
                        required
                        disabled={busy}
                      />
                    </label>

                    <label className="api-field">
                      <span>接口类型</span>
                      <select
                        className="input"
                        value={form.kind}
                        onChange={(event) =>
                          setForm({ ...form, kind: event.target.value as 'openai' | 'anthropic' })
                        }
                        disabled={busy}
                      >
                        <option value="openai">OpenAI 兼容</option>
                        <option value="anthropic">Anthropic</option>
                      </select>
                    </label>

                    <label className={'api-field api-field-full' + (readySteps.url ? ' is-filled' : '')}>
                      <span>
                        Base URL
                        {readySteps.url && <i className="api-field-ok" aria-hidden="true" />}
                      </span>
                      <input
                        className="input"
                        value={form.base_url}
                        onChange={(event) => {
                          clearProbeEcho()
                          setForm({ ...form, base_url: event.target.value })
                        }}
                        placeholder="http://127.0.0.1:3000/v1"
                        disabled={busy}
                      />
                    </label>

                    <label className={'api-field api-field-full' + (readySteps.key ? ' is-filled' : '')}>
                      <span>
                        API Key / 令牌
                        {readySteps.key ? (
                          <i className="api-field-ok" aria-hidden="true" />
                        ) : (
                          <em className="api-field-need">必填</em>
                        )}
                      </span>
                      <div className="api-key-row">
                        <input
                          className="input"
                          type={showKey ? 'text' : 'password'}
                          value={form.api_key}
                          onChange={(event) => {
                            clearProbeEcho()
                            setForm({ ...form, api_key: event.target.value })
                          }}
                          placeholder="sk-…"
                          autoComplete="off"
                          disabled={busy}
                        />
                        <button
                          type="button"
                          className="api-key-toggle"
                          onClick={() => setShowKey((value) => !value)}
                          disabled={busy || !form.api_key}
                        >
                          {showKey ? '隐藏' : '显示'}
                        </button>
                      </div>
                    </label>

                    <label className={'api-field api-field-full' + (readySteps.model ? ' is-filled' : '')}>
                      <span>
                        模型 ID
                        {readySteps.model ? (
                          <i className="api-field-ok" aria-hidden="true" />
                        ) : (
                          <em className="api-field-need">必填</em>
                        )}
                      </span>
                      <div className="api-model-row">
                        <input
                          className="input"
                          value={form.model}
                          onChange={(event) => setForm({ ...form, model: event.target.value })}
                          placeholder="选择或手填模型名"
                          required
                          disabled={busy}
                        />
                        <button
                          type="button"
                          className="btn"
                          disabled={busy || !form.base_url}
                          onClick={() => void onListModels()}
                        >
                          拉取
                        </button>
                      </div>
                    </label>

                    <div className="api-form-actions">
                      <div className="api-ready" aria-label="接线进度">
                        <span className={'api-ready-step' + (readySteps.url ? ' is-on' : '')}>地址</span>
                        <span className={'api-ready-step' + (readySteps.key ? ' is-on' : '')}>Key</span>
                        <span className={'api-ready-step' + (readySteps.model ? ' is-on' : '')}>模型</span>
                        <em className={'api-ready-meta' + (formReady ? ' is-ok' : '')}>
                          {formReady ? '可接通' : `${readyCount}/3`}
                        </em>
                      </div>
                      <div className="api-form-btns">
                        <button
                          type="submit"
                          className={'btn btn-primary' + (formReady ? ' is-ready-cta' : '')}
                          disabled={busy || !formReady}
                          title={formReady ? undefined : '请先填完地址、Key 与模型'}
                        >
                          {busy ? '处理中…' : form.id ? '保存修改' : '保存并接通'}
                        </button>
                        <button
                          type="button"
                          className={'btn' + (probing ? ' is-probing-btn' : '')}
                          disabled={busy}
                          onClick={() => void onProbeGateway()}
                        >
                          {probing ? '探测中…' : '探测网关'}
                        </button>
                        {form.id && (
                          <button type="button" className="btn btn-ghost" disabled={busy} onClick={resetForm}>
                            取消
                          </button>
                        )}
                      </div>
                    </div>
                  </form>

                  {models.length > 0 && (
                    <div className="api-models" aria-label="可选模型">
                      <div className="api-models-head">
                        <h4>点选填入模型</h4>
                        <span>{models.length}</span>
                      </div>
                      <div className="api-model-scroll">
                        {models.map((model) => {
                          const selected = form.model === model.id
                          return (
                            <button
                              key={model.id}
                              type="button"
                              className={'api-model-row-item' + (selected ? ' is-on' : '')}
                              onClick={() => setForm((current) => ({ ...current, model: model.id }))}
                            >
                              <span>{model.display_name || model.id}</span>
                              {model.owned_by ? <small>{model.owned_by}</small> : null}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  )
}

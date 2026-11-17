import { useState } from 'react'
import CanvasRatioSelect from './CanvasRatioSelect'
import type { CanvasRatio, DiagramKind, DiagramLayout, ImageFormat, RenderResult } from '../types'
import DragOverlay from './DragOverlay'
import { useLocale } from '../LocaleContext'

interface PreviewPanelProps {
  result: RenderResult | null
  loading: boolean
  generating: boolean
  emptyDraft: boolean
  /** 编辑内容与上次出图不一致 */
  stale: boolean
  formatOnly: boolean
  hasSavedLayout: boolean
  renderLabel: string
  blocked: boolean
  tab: string
  format: ImageFormat
  onFormatChange: (format: ImageFormat) => void
  ratio: CanvasRatio
  ratioPending: boolean
  onRatioChange: (ratio: CanvasRatio) => void
  onApplyRatio: () => void
  onTabChange: (tab: string) => void
  onRender: () => void
  onResetLayout: () => void
  onMoveEntity: (entity: string, x: number, y: number) => void
  onDownloadAll: () => void
  onDownloadOne: (url: string, filename: string) => void
  onLoadSample?: () => void
  sampleLabel?: string
  loggedIn?: boolean
  onLogin?: () => void
  diagramKind?: DiagramKind
  /** 用例图等：规格就绪但后端出图未接通 */
  backendPending?: boolean
}

export default function PreviewPanel({
  result,
  loading,
  generating,
  emptyDraft,
  stale,
  formatOnly,
  hasSavedLayout,
  renderLabel,
  blocked,
  tab,
  format,
  onFormatChange,
  ratio,
  ratioPending,
  onRatioChange,
  onApplyRatio,
  onTabChange,
  onRender,
  onResetLayout,
  onMoveEntity,
  onDownloadAll,
  onDownloadOne,
  onLoadSample,
  sampleLabel,
  loggedIn = true,
  onLogin,
  diagramKind = 'er',
  backendPending = false,
}: PreviewPanelProps) {
  const { locale, app } = useLocale()
  const p = app.preview
  const [broken, setBroken] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<string | null>(null)
  const [adjusting, setAdjusting] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const isUseCase = diagramKind === 'usecase'

  const entityResults = result?.entities ?? []
  const tabs = result
    ? [
        { key: 'overview', label: isUseCase ? p.overviewUc : p.overviewEr },
        ...entityResults.map((entry) => ({ key: entry.entity, label: p.attrOf(entry.entity) })),
      ]
    : [{ key: 'overview', label: isUseCase ? p.overviewUc : p.overviewEr }]

  const activeKey = tabs.some((entry) => entry.key === tab) ? tab : 'overview'
  const active =
    result && activeKey !== 'overview'
      ? entityResults.find((entry) => entry.entity === activeKey)
      : result?.overview ?? null
  const total = result ? entityResults.length + 1 : 0
  const layout: DiagramLayout | undefined = result?.layout
  const layoutEntities = layout?.entities ?? []
  const canExpand =
    activeKey === 'overview' && !!layout && (layoutEntities.length > 15 || layout.width > 12 || layout.height > 9)
  const zoomed = expanded && canExpand
  const quality = layout?.quality
  const useCaseQuality = isUseCase ? layout?.useCaseQuality : undefined
  const useCaseConflicts =
    useCaseQuality &&
    useCaseQuality.overlaps + useCaseQuality.boxHits + useCaseQuality.lineConflicts + useCaseQuality.labelConflicts > 0
  const verified =
    quality?.planar && !(quality.overlaps || quality.boxHits || quality.lineConflicts || quality.labelConflicts)
  let qualityLabel = ''
  if (quality) {
    if (!quality.planar) qualityLabel = p.planarFail
    else if (verified)
      qualityLabel = layout?.referenceCount ? p.planarRefs(layout.referenceCount) : p.planarOk
    else if (quality.lineConflicts) qualityLabel = p.planarConflicts(quality.lineConflicts)
    else qualityLabel = p.planarBlocked
  }
  const adjustingOverview = adjusting && activeKey === 'overview'
  const canAdjust = !!layout && layoutEntities.length > 0 && !stale && !loading && !generating
  const showOverlay = adjustingOverview && canAdjust && loaded === result?.overview.url

  const timeText = result
    ? new Date(result.renderedAt).toLocaleTimeString(locale === 'en' ? 'en-US' : 'zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : ''

  return (
    <section className="panel preview" id="preview-panel">
      <div className="preview-head">
        <div className="tabs" role="tablist" aria-label={p.tabsAria}>
          {tabs.map((entry) => (
            <button
              key={entry.key}
              type="button"
              role="tab"
              aria-selected={entry.key === activeKey}
              className={`tab${entry.key === activeKey ? ' is-active' : ''}`}
              onClick={() => onTabChange(entry.key)}
              data-testid={`tab-${entry.key}`}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <div className="preview-actions">
          {useCaseQuality && (
            <span
              className={`badge ${useCaseConflicts ? 'badge-warn' : 'badge-quiet'}`}
              data-testid="usecase-layout-quality"
              title={`line ${useCaseQuality.lineConflicts} · box ${useCaseQuality.boxHits} · overlap ${useCaseQuality.overlaps} · label ${useCaseQuality.labelConflicts}`}
            >
              {useCaseConflicts ? p.conflictDrag : p.routedOk}
            </span>
          )}
          {activeKey === 'overview' && quality && (
            <span
              className={`badge ${verified ? 'badge-quiet' : 'badge-warn'}`}
              title={`line ${quality.lineConflicts} · box ${quality.boxHits} · overlap ${quality.overlaps} · label ${quality.labelConflicts}`}
              data-testid="layout-quality"
            >
              {qualityLabel}
            </span>
          )}
          {stale && (
            <span className="badge badge-warn" data-testid="stale-badge">
              {ratioPending
                ? p.pendingRatio
                : formatOnly
                  ? p.pendingFormat
                  : hasSavedLayout
                    ? p.pendingEditLayout
                    : p.pendingEditRelayout}
            </span>
          )}

          <div className="preview-tools">
            {result && (
              <button
                type="button"
                className="btn btn-sm"
                aria-pressed={adjustingOverview}
                disabled={!canAdjust}
                title={stale || !layout ? p.needRenderFirst : isUseCase ? p.dragUc : p.dragEr}
                onClick={() => {
                  onTabChange('overview')
                  setAdjusting(!adjustingOverview)
                }}
              >
                {adjustingOverview ? p.endAdjust : p.startAdjust}
              </button>
            )}
            {canExpand && (
              <button type="button" className="btn btn-sm" aria-pressed={zoomed} onClick={() => setExpanded(!expanded)}>
                {zoomed ? p.fitWindow : p.zoomIn}
              </button>
            )}
            {(result || hasSavedLayout) && (
              <button
                type="button"
                className="btn btn-sm"
                disabled={loading || generating || blocked}
                onClick={onResetLayout}
              >
                {p.resetLayout}
              </button>
            )}
          </div>
        </div>
      </div>

      {showOverlay && <p className="layout-hint">{isUseCase ? p.dragHintUc : p.dragHintEr}</p>}
      <div
        className={`stage${zoomed ? ' is-zoomed' : ''}${active ? '' : ' is-empty'}${loading || generating ? ' is-busy' : ''}`}
        aria-busy={loading || generating}
      >
        {active ? (
          broken === active.url ? (
            <div className="empty">
              <p className="empty-title">{p.brokenTitle}</p>
              <p className="hint">{p.brokenHint}</p>
            </div>
          ) : (
            <div className="preview-figure" style={zoomed && layout ? { width: layout.width * 96 } : undefined}>
              <img
                key={active.url}
                src={active.url}
                alt={active.filename}
                className="preview-image"
                data-testid="preview-image"
                draggable={false}
                onError={() => setBroken(active.url)}
                onLoad={() => {
                  setBroken(null)
                  setLoaded(active.url)
                }}
              />
              {showOverlay && layout && <DragOverlay layout={layout} onMove={onMoveEntity} />}
            </div>
          )
        ) : (
          <div className={`empty${emptyDraft ? ' is-cold' : ''}`} data-testid="preview-empty">
            {emptyDraft && !isUseCase && (
              <svg className="empty-sketch" viewBox="0 0 360 132" aria-hidden="true">
                <line className="sketch-line" x1="78" y1="28" x2="78" y2="52" />
                <line className="sketch-line" x1="118" y1="78" x2="156" y2="78" />
                <line className="sketch-line" x1="204" y1="78" x2="242" y2="78" />
                <ellipse cx="78" cy="16" rx="30" ry="15" />
                <text x="78" y="16">
                  姓名
                </text>
                <rect x="36" y="52" width="84" height="36" rx="2" />
                <text x="78" y="70">
                  读者
                </text>
                <polygon points="180,56 204,78 180,100 156,78" />
                <text x="180" y="78">
                  借阅
                </text>
                <rect x="242" y="60" width="84" height="36" rx="2" />
                <text x="284" y="78">
                  图书
                </text>
                <text className="sketch-card" x="136" y="70">
                  n
                </text>
                <text className="sketch-card" x="220" y="70">
                  m
                </text>
              </svg>
            )}
            {emptyDraft && isUseCase && (
              <svg className="empty-sketch" viewBox="0 0 360 132" aria-hidden="true">
                <ellipse cx="56" cy="66" rx="18" ry="12" />
                <line x1="56" y1="78" x2="56" y2="102" />
                <line x1="56" y1="86" x2="40" y2="96" />
                <line x1="56" y1="86" x2="72" y2="96" />
                <line x1="56" y1="102" x2="44" y2="118" />
                <line x1="56" y1="102" x2="68" y2="118" />
                <text x="56" y="128">
                  读者
                </text>
                <line className="sketch-line" x1="78" y1="66" x2="140" y2="66" />
                <rect x="140" y="24" width="160" height="84" rx="4" />
                <text x="220" y="40">
                  图书借阅系统
                </text>
                <ellipse cx="220" cy="70" rx="48" ry="22" />
                <text x="220" y="74">
                  借书
                </text>
              </svg>
            )}
            <p className="empty-title">
              {emptyDraft ? p.emptyStart : backendPending ? p.emptyReady : p.emptyNone}
            </p>
            {emptyDraft ? (
              <>
                <p className="hint">{isUseCase ? p.emptyHintUc : p.emptyHintEr}</p>
                {onLoadSample && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={onLoadSample}
                    disabled={loading || generating}
                    data-testid="preview-load-sample"
                  >
                    {sampleLabel || (isUseCase ? app.loadSampleUc : app.loadSampleEr)}
                  </button>
                )}
              </>
            ) : backendPending ? (
              <>
                <p className="hint" data-testid="preview-backend-pending">
                  {p.pendingBackend}
                </p>
                <button type="button" className="btn" disabled title={p.pendingApi}>
                  {p.pendingBackendBtn}
                </button>
              </>
            ) : !loggedIn && onLogin ? (
              <>
                <p className="hint">{p.readyLogin}</p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={onLogin}
                  disabled={loading || generating}
                  data-testid="preview-login"
                >
                  {app.goLogin}
                </button>
              </>
            ) : (
              <>
                <p className="hint">{p.readyRender}</p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={onRender}
                  disabled={loading || generating || blocked}
                >
                  {renderLabel}
                </button>
              </>
            )}
          </div>
        )}

        {(loading || generating) && (
          <div className="stage-loading" data-testid="preview-loading" role="status">
            <div className="stage-loading-card">
              <span className="spinner" aria-hidden="true" />
              <div className="stage-loading-copy">
                <strong>{loading ? p.busyLayout : p.busyGen}</strong>
                <span>
                  {loading ? (isUseCase ? p.soonUc : p.soonEr) : isUseCase ? p.modelUc : p.modelEr}
                </span>
              </div>
              <div className="stage-loading-bar" aria-hidden="true">
                <i />
              </div>
            </div>
          </div>
        )}
      </div>

      {!emptyDraft || result ? (
        <div className={`preview-foot${result ? ' has-result' : ' is-pending'}`}>
          <div className="foot-meta">
            {result ? (
              <>
                <code className="file-name">{active ? active.filename : '—'}</code>
                <span className="muted">{p.figuresCount(total, timeText)}</span>
              </>
            ) : (
              <span className="muted">{p.footHint(renderLabel)}</span>
            )}
          </div>

          {result ? (
            <div className="foot-actions">
              <div className="foot-settings" role="group" aria-label={p.exportSettings}>
                <span className="foot-label">{p.format}</span>
                <div className="segmented" role="group" aria-label={p.imageFormat}>
                  {(['png', 'svg'] as ImageFormat[]).map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={`seg${format === option ? ' is-active' : ''}`}
                      aria-pressed={format === option}
                      onClick={() => onFormatChange(option)}
                      disabled={loading || generating}
                      title={
                        format === option
                          ? p.currentFormat(option.toUpperCase())
                          : p.changeFormat(option.toUpperCase())
                      }
                      data-testid={`format-${option}`}
                    >
                      {option.toUpperCase()}
                    </button>
                  ))}
                </div>
                <CanvasRatioSelect ratio={ratio} onChange={onRatioChange} disabled={loading || generating} />
                {ratioPending && (
                  <button type="button" className="btn btn-sm" onClick={onApplyRatio} disabled={loading || generating}>
                    {p.applyRatio}
                  </button>
                )}
              </div>
              <div className="foot-download">
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  onClick={() => active && onDownloadOne(active.url, active.filename)}
                  disabled={!active || loading || ratioPending}
                  data-testid="download-current"
                >
                  {p.downloadCurrent}
                </button>
                <button
                  type="button"
                  className="link-btn"
                  onClick={onDownloadAll}
                  disabled={!total || loading || ratioPending}
                  data-testid="download-all"
                >
                  {p.downloadAllCount(total)}
                </button>
              </div>
            </div>
          ) : (
            <div className="foot-actions foot-actions-pending">
              <span className="foot-label">{p.nextFormat}</span>
              <div className="segmented" role="group" aria-label={p.imageFormat}>
                {(['png', 'svg'] as ImageFormat[]).map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`seg${format === option ? ' is-active' : ''}`}
                    aria-pressed={format === option}
                    onClick={() => onFormatChange(option)}
                    disabled={loading || generating}
                    title={
                      format === option
                        ? p.currentFormat(option.toUpperCase())
                        : p.changeFormat(option.toUpperCase())
                    }
                    data-testid={`format-${option}`}
                  >
                    {option.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </section>
  )
}

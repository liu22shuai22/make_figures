import { useState } from 'react'
import CanvasRatioSelect from './CanvasRatioSelect'
import type { CanvasRatio, DiagramLayout, ImageFormat, RenderResult } from '../types'
import DragOverlay from './DragOverlay'

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
  loggedIn?: boolean
  onLogin?: () => void
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
  loggedIn = true,
  onLogin,
}: PreviewPanelProps) {
  const [broken, setBroken] = useState<string | null>(null)
  const [loaded, setLoaded] = useState<string | null>(null)
  const [adjusting, setAdjusting] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const tabs = result
    ? [{ key: 'overview', label: '整体 E-R 图' }, ...result.entities.map((entry) => ({ key: entry.entity, label: `${entry.entity}属性图` }))]
    : [{ key: 'overview', label: '整体 E-R 图' }]

  const activeKey = tabs.some((entry) => entry.key === tab) ? tab : 'overview'
  const active =
    result && activeKey !== 'overview' ? result.entities.find((entry) => entry.entity === activeKey) : result?.overview ?? null
  const total = result ? result.entities.length + 1 : 0
  const layout: DiagramLayout | undefined = result?.layout
  const canExpand = activeKey === 'overview' && !!layout &&
    (layout.entities.length > 15 || layout.width > 12 || layout.height > 9)
  const zoomed = expanded && canExpand
  const quality = layout?.quality
  const verified = quality?.planar && !(quality.overlaps || quality.boxHits || quality.lineConflicts || quality.labelConflicts)
  let qualityLabel = ''
  if (quality) {
    if (!quality.planar) qualityLabel = '完整单图无法零交叉'
    else if (verified) qualityLabel = layout?.referenceCount
      ? `零交叉 · ${layout.referenceCount} 个同名引用框`
      : '零交叉 · 已验证'
    else if (quality.lineConflicts) qualityLabel = `可零交叉 · 当前有 ${quality.lineConflicts} 处连线冲突`
    else qualityLabel = '零交叉 · 仍有遮挡'
  }
  const adjustingOverview = adjusting && activeKey === 'overview'
  const canAdjust = !!layout && !stale && !loading && !generating
  const showOverlay = adjustingOverview && canAdjust && loaded === result?.overview.url

  const timeText = result
    ? new Date(result.renderedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : ''

  return (
    <section className="panel preview" id="preview-panel">
      {/* 第一层：图的切换（整体图 / 各实体属性图） */}
      <div className="preview-head">
        <div className="tabs" role="tablist" aria-label="预览切换">
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

        {/* 第二层：只放「对这张图」的查看与布局操作 */}
        <div className="preview-actions">
          {activeKey === 'overview' && quality && (
            <span
              className={`badge ${verified ? 'badge-quiet' : 'badge-warn'}`}
              title={`连线冲突 ${quality.lineConflicts}，穿框 ${quality.boxHits}，图形挤压 ${quality.overlaps}，基数遮挡 ${quality.labelConflicts}`}
              data-testid="layout-quality"
            >
              {qualityLabel}
            </span>
          )}
          {stale && (
            <span className="badge badge-warn" data-testid="stale-badge">
              {ratioPending ? '待应用画布比例' : formatOnly ? '待更新图片格式' : hasSavedLayout ? '有修改，待出图' : '有修改，待重新排版'}
            </span>
          )}

          <div className="preview-tools">
            {result && (
              <button
                type="button"
                className="btn btn-sm"
                aria-pressed={adjustingOverview}
                disabled={!canAdjust}
                title={stale || !layout ? '请先为当前规格出图' : '在整体 E-R 图上移动实体'}
                onClick={() => {
                  onTabChange('overview')
                  setAdjusting(!adjustingOverview)
                }}
              >
                {adjustingOverview ? '结束微调' : '拖拽微调'}
              </button>
            )}
            {canExpand && (
              <button type="button" className="btn btn-sm" aria-pressed={zoomed} onClick={() => setExpanded(!expanded)}>
                {zoomed ? '适应窗口' : '放大查看'}
              </button>
            )}
            {(result || hasSavedLayout) && (
              <button type="button" className="btn btn-sm" disabled={loading || generating || blocked} onClick={onResetLayout}>
                恢复自动排版
              </button>
            )}
          </div>
        </div>
      </div>

      {showOverlay && <p className="layout-hint">拖动实体，松开后更新连线和基数。也可聚焦实体后用方向键移动。</p>}
      <div
        className={`stage${zoomed ? ' is-zoomed' : ''}${active ? '' : ' is-empty'}${loading || generating ? ' is-busy' : ''}`}
        aria-busy={loading || generating}
      >
        {active ? (
          broken === active.url ? (
            <div className="empty">
              <p className="empty-title">图片没能显示</p>
              <p className="hint">浏览器拒绝了这张图片，可以尝试重新排版，或下载后本地查看。</p>
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
            {emptyDraft && (
              <svg className="empty-sketch" viewBox="0 0 360 132" aria-hidden="true">
                <line className="sketch-line" x1="78" y1="28" x2="78" y2="52" />
                <line className="sketch-line" x1="118" y1="78" x2="156" y2="78" />
                <line className="sketch-line" x1="204" y1="78" x2="242" y2="78" />
                <ellipse cx="78" cy="16" rx="30" ry="15" />
                <text x="78" y="16">姓名</text>
                <rect x="36" y="52" width="84" height="36" rx="2" />
                <text x="78" y="70">读者</text>
                <polygon points="180,56 204,78 180,100 156,78" />
                <text x="180" y="78">借阅</text>
                <rect x="242" y="60" width="84" height="36" rx="2" />
                <text x="284" y="78">图书</text>
                <text className="sketch-card" x="136" y="70">n</text>
                <text className="sketch-card" x="220" y="70">m</text>
              </svg>
            )}
            <p className="empty-title">{emptyDraft ? '从描述开始' : '还没有图'}</p>
            {emptyDraft ? (
              <>
                <p className="hint">在描述区写一段，或载入选课样例出图。</p>
                {onLoadSample && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={onLoadSample}
                    disabled={loading || generating}
                    data-testid="preview-load-sample"
                  >
                    载入选课样例
                  </button>
                )}
              </>
            ) : !loggedIn && onLogin ? (
              <>
                <p className="hint">规格已就绪，登录后即可出图。</p>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={onLogin}
                  disabled={loading || generating}
                  data-testid="preview-login"
                >
                  去登录
                </button>
              </>
            ) : (
              <>
                <p className="hint">规格已就绪，点下方出图。</p>
                <button type="button" className="btn btn-primary" onClick={onRender} disabled={loading || generating || blocked}>
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
                <strong>{loading ? '正在排版出图' : '正在生成规格'}</strong>
                <span>
                  {loading
                    ? '马上出现整体 E-R 图与实体属性图'
                    : '模型整理实体与联系，完成后自动排版'}
                </span>
              </div>
              <div className="stage-loading-bar" aria-hidden="true">
                <i />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 第三层：有图时下载为主，格式/比例次之；冷启动不占脚栏 */}
      {!emptyDraft || result ? (
        <div className={`preview-foot${result ? ' has-result' : ' is-pending'}`}>
          <div className="foot-meta">
            {result ? (
              <>
                <code className="file-name">{active ? active.filename : '—'}</code>
                <span className="muted">
                  {total} 张 · {timeText}
                </span>
              </>
            ) : (
              <span className="muted">修改后点「{renderLabel}」；出图后可下载</span>
            )}
          </div>

          {result ? (
            <div className="foot-actions">
              <div className="foot-settings" role="group" aria-label="导出设置">
                <span className="foot-label">格式</span>
                <div className="segmented" role="group" aria-label="图片格式">
                  {(['png', 'svg'] as ImageFormat[]).map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={`seg${format === option ? ' is-active' : ''}`}
                      aria-pressed={format === option}
                      onClick={() => onFormatChange(option)}
                      disabled={loading || generating}
                      title={format === option ? `当前 ${option.toUpperCase()}` : `改为 ${option.toUpperCase()}`}
                      data-testid={`format-${option}`}
                    >
                      {option.toUpperCase()}
                    </button>
                  ))}
                </div>
                <CanvasRatioSelect ratio={ratio} onChange={onRatioChange} disabled={loading || generating} />
                {ratioPending && (
                  <button type="button" className="btn btn-sm" onClick={onApplyRatio} disabled={loading || generating}>
                    应用比例
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
                  下载当前
                </button>
                <button
                  type="button"
                  className="link-btn"
                  onClick={onDownloadAll}
                  disabled={!total || loading || ratioPending}
                  data-testid="download-all"
                >
                  全部 {total} 张
                </button>
              </div>
            </div>
          ) : (
            <div className="foot-actions foot-actions-pending">
              <span className="foot-label">下次格式</span>
              <div className="segmented" role="group" aria-label="图片格式">
                {(['png', 'svg'] as ImageFormat[]).map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`seg${format === option ? ' is-active' : ''}`}
                    aria-pressed={format === option}
                    onClick={() => onFormatChange(option)}
                    disabled={loading || generating}
                    title={format === option ? `当前 ${option.toUpperCase()}` : `改为 ${option.toUpperCase()}`}
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

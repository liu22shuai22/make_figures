import BrandMark from './BrandMark'
import { REPO_URL } from '../site'

interface SiteFooterProps {
  /** 「首页」链接；不传则不显示 */
  onHome?: () => void
  /** 「工作台」链接；不传则不显示 */
  onWorkbench?: () => void
  /** 底栏右侧的小字说明，按页面语境定制 */
  note?: string
  badge?: string
  tagline?: string
  navLabel?: string
  homeLabel?: string
  workbenchLabel?: string
  freeLabel?: string
  sgiLabel?: string
}

/**
 * 欢迎页共用的页脚：
 * 上行 = 品牌块 + 导航；下行 = 版权与本地/渠道说明。
 */
export default function SiteFooter({
  onHome,
  onWorkbench,
  note = '规格与出图在本机完成；生成仅发往你接入的模型渠道',
  badge = '公测',
  tagline = '自然语言凝成可编辑的结构 · 语义沙',
  navLabel = '页脚导航',
  homeLabel = '首页',
  workbenchLabel = '工作台',
  freeLabel = '免费使用',
  sgiLabel = '通向SGI',
}: SiteFooterProps) {
  const year = new Date().getFullYear()
  return (
    <footer className="welcome-foot" data-reveal>
      <div className="foot-inner">
        <div className="foot-grid">
          <div className="foot-brand">
            <BrandMark size={34} />
            <div className="foot-brand-text">
              <div className="foot-brand-row">
                <strong>ERFlow</strong>
                <span className="foot-badge">{badge}</span>
              </div>
              <p>{tagline}</p>
            </div>
          </div>
          <nav className="foot-nav" aria-label={navLabel}>
            {onHome && (
              <button type="button" className="link-btn" onClick={onHome}>
                {homeLabel}
              </button>
            )}
            {onWorkbench && (
              <button type="button" className="link-btn" onClick={onWorkbench}>
                {workbenchLabel}
              </button>
            )}
            <a className="link-btn" href={REPO_URL} target="_blank" rel="noreferrer noopener">
              GitHub
            </a>
            <span className="foot-sgi" title={sgiLabel}>
              {sgiLabel}
            </span>
          </nav>
        </div>
        <div className="foot-bar">
          <p className="foot-copy">
            <span>© {year} ERFlow</span>
            <span className="foot-copy-sep" aria-hidden="true" />
            <span>{freeLabel}</span>
          </p>
          <p className="foot-note">{note}</p>
        </div>
      </div>
    </footer>
  )
}

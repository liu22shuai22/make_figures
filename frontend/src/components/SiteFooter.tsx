import BrandMark from './BrandMark'
import { REPO_URL } from '../site'

interface SiteFooterProps {
  /** 「首页」链接；不传则不显示 */
  onHome?: () => void
  /** 「工作台」链接；不传则不显示 */
  onWorkbench?: () => void
  /** 底栏右侧的小字说明，按页面语境定制 */
  note?: string
}

/**
 * 欢迎页共用的页脚：
 * 上行 = 品牌块（徽标 + 名称 + 一句话定位）+ 页脚导航；下行 = 版权 + 小字说明。
 */
export default function SiteFooter({
  onHome,
  onWorkbench,
  note = '规格与出图均在本地服务完成，不上传第三方',
}: SiteFooterProps) {
  const year = new Date().getFullYear()
  return (
    <footer className="welcome-foot" data-reveal>
      <div className="foot-inner">
        <div className="foot-grid">
          <div className="foot-brand">
            <BrandMark size={36} />
            <div className="foot-brand-text">
              <div className="foot-brand-row">
                <strong>ERFlow</strong>
                <span className="foot-badge">公测</span>
              </div>
              <p>自然语言凝成可编辑的结构 · 语义沙</p>
            </div>
          </div>
          <nav className="foot-nav" aria-label="页脚导航">
            {onHome && (
              <button type="button" className="link-btn" onClick={onHome}>
                首页
              </button>
            )}
            {onWorkbench && (
              <button type="button" className="link-btn" onClick={onWorkbench}>
                工作台
              </button>
            )}
            <a className="link-btn" href={REPO_URL} target="_blank" rel="noreferrer noopener">
              GitHub
            </a>
            <span className="foot-sgi" title="通向SGI">
              通向SGI
            </span>
          </nav>
        </div>
        <div className="foot-bar">
          <span>© {year} ERFlow · 免费使用</span>
          <span className="foot-note">{note}</span>
        </div>
      </div>
    </footer>
  )
}

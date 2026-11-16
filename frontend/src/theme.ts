export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'erflow-theme'

/** 默认浅色（与既有视觉一致），用户选过就按记录的来 */
export function readTheme(): Theme {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    // 隐私模式下 localStorage 可能不可用，忽略即可
  }
  return 'light'
}

/**
 * 主题落在 <html data-theme> 上，由 CSS 变量接管颜色。
 * persist=false 用于首次挂载：只应用，不覆写用户尚未做的选择。
 */
export function applyTheme(theme: Theme, persist = true) {
  document.documentElement.setAttribute('data-theme', theme)
  if (!persist) return
  try {
    window.localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // 写不进去不影响本次显示
  }
}

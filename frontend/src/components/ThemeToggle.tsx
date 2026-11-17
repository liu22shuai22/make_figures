import type { Theme } from '../theme'
import { useLocale } from '../LocaleContext'

interface ThemeToggleProps {
  theme: Theme
  onToggle: () => void
}

/** 顶栏主题切换：太阳/月亮图标，状态通过 aria-pressed 暴露 */
export default function ThemeToggle({ theme, onToggle }: ThemeToggleProps) {
  const { app } = useLocale()
  const dark = theme === 'dark'
  const label = dark ? app.themeToLight : app.themeToDark

  return (
    <button
      type="button"
      className="icon-ghost"
      onClick={onToggle}
      aria-label={label}
      aria-pressed={dark}
      title={label}
      data-testid="theme-toggle"
    >
      {dark ? (
        <svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <circle cx="10" cy="10" r="3.6" stroke="currentColor" strokeWidth="1.6" />
          <path
            d="M10 1.6v1.7M10 16.7v1.7M18.4 10h-1.7M3.3 10H1.6M15.94 4.06l-1.2 1.2M5.26 14.74l-1.2 1.2M15.94 15.94l-1.2-1.2M5.26 5.26l-1.2-1.2"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg width="17" height="17" viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path
            d="M16.5 12.4A7 7 0 0 1 7.6 3.5a7.2 7.2 0 1 0 8.9 8.9Z"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  )
}

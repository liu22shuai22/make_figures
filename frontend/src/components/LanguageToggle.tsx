import type { Locale } from '../locale'
import { useLocale } from '../LocaleContext'

interface Props {
  /** 不传则用全局 LocaleContext（整站同一套语言） */
  locale?: Locale
  onChange?: (locale: Locale) => void
}

/** 只放在欢迎页顶栏；改的是整站 locale，其他页不重复放开关 */
export default function LanguageToggle({ locale: localeProp, onChange }: Props) {
  const ctx = useLocale()
  const locale = localeProp ?? ctx.locale
  const change = onChange ?? ctx.setLocale
  return (
    <div className="lang-toggle" role="group" aria-label={locale === 'zh' ? '切换语言' : 'Language'}>
      <button
        type="button"
        className={'lang-toggle-btn' + (locale === 'zh' ? ' is-active' : '')}
        aria-pressed={locale === 'zh'}
        onClick={() => change('zh')}
        data-testid="lang-zh"
      >
        中
      </button>
      <button
        type="button"
        className={'lang-toggle-btn' + (locale === 'en' ? ' is-active' : '')}
        aria-pressed={locale === 'en'}
        onClick={() => change('en')}
        data-testid="lang-en"
      >
        EN
      </button>
    </div>
  )
}

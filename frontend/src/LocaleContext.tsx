import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { applyLocale, readLocale, welcomeCopy, type Locale, type WelcomeCopy } from './locale'
import { appCopy, type AppCopy } from './appLocale'

interface LocaleContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  welcome: WelcomeCopy
  app: AppCopy
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

/** 整站共用一套语言；顶栏「中 / EN」改的就是这里 */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readLocale)

  useEffect(() => {
    applyLocale(locale, false)
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    applyLocale(next)
    setLocaleState(next)
  }, [])

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      setLocale,
      welcome: welcomeCopy[locale],
      app: appCopy[locale],
    }),
    [locale, setLocale],
  )

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext)
  if (!ctx) throw new Error('useLocale 必须在 LocaleProvider 内使用')
  return ctx
}

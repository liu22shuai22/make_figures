import { StrictMode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import Welcome from './Welcome'
import TokenUsage from './TokenUsage'
import ApiPlatform from './ApiPlatform'
import AuthPage from './AuthPage'
import AiAssistant from './components/AiAssistant'
import type { AssistantDraft } from './components/ModelAssistant'
import './styles.css'
import { applyTheme, readTheme } from './theme'
import type { Theme } from './theme'
import { clearSession, loadSession, logoutSession, verifySession } from './auth'
import type { AuthSession } from './auth'
import type { WorkbenchCommand } from './types'

const container = document.getElementById('root')
if (!container) throw new Error('找不到 #root 挂载点')

const WORKBENCH = '/workbench'
const USAGE = '/usage'
const API_PLATFORM = '/api-platform'
const LOGIN = '/login'
const REGISTER = '/register'
const HOME = '/'

const normalize = (pathname: string) => {
  const path = pathname.replace(/\/+$/, '')
  if (path === WORKBENCH || path === USAGE || path === API_PLATFORM || path === LOGIN || path === REGISTER) {
    return path
  }
  return HOME
}

type Route = typeof HOME | typeof WORKBENCH | typeof USAGE | typeof API_PLATFORM | typeof LOGIN | typeof REGISTER
function Root() {
  const [route, setRoute] = useState<Route>(() => normalize(window.location.pathname))
  const [command, setCommand] = useState<WorkbenchCommand | null>(null)
  const [theme, setTheme] = useState<Theme>(readTheme)
  const [auth, setAuth] = useState<AuthSession | null>(() => loadSession())
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [assistantDraft, setAssistantDraft] = useState<AssistantDraft>()
  const [assistantTarget, setAssistantTarget] = useState<string>()
  const nonce = useRef(0)

  // 首帧对齐 index.html 里预设的 data-theme，避免闪一下浅色
  useEffect(() => {
    applyTheme(theme, false)
  }, [theme])

  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  useEffect(() => {
    const onPopState = () => setRoute(normalize(window.location.pathname))
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    document.title = route === USAGE ? 'ERFlow Token 用量'
      : route === API_PLATFORM ? 'ERFlow API 平台'
      : route === WORKBENCH ? 'ERFlow 工作台'
      : route === LOGIN ? 'ERFlow 登录'
      : route === REGISTER ? 'ERFlow 注册'
      : 'ERFlow · 用自然语言生成 E-R 图'
  }, [route])

  useEffect(() => {
    if (!auth) return
    let cancelled = false
    let checking = false
    const check = async () => {
      if (checking || cancelled) return
      checking = true
      const valid = await verifySession(auth)
      checking = false
      if (!cancelled && valid === false) {
        clearSession(auth)
        setAuth((current) => current?.token === auth.token ? null : current)
      }
    }
    void check()
    window.addEventListener('focus', check)
    window.addEventListener('online', check)
    return () => {
      cancelled = true
      window.removeEventListener('focus', check)
      window.removeEventListener('online', check)
    }
  }, [auth])

  const handleLogout = () => {
    if (auth) void logoutSession(auth)
    setAuth(null)
  }

  // 保留工作台的挂载状态，切换页面时可以继续编辑原草稿。
  const go = (next: Route, action?: WorkbenchCommand['type']) => {
    if (window.location.pathname !== next) window.history.pushState(null, '', next)
    setRoute(next)
    if (action) {
      nonce.current += 1
      setCommand({ type: action, nonce: nonce.current })
    }
  }

  useLayoutEffect(() => {
    if (route !== WORKBENCH || !assistantTarget || !assistantDraft) return
    assistantDraft.onLocate(assistantTarget)
    setAssistantTarget(undefined)
  }, [route, assistantTarget, assistantDraft])

  return (
    <>
      <div hidden={route !== HOME}>
        <Welcome
          onStart={() => go(WORKBENCH, 'focus')}
          onSample={() => go(WORKBENCH, 'sample')}
          onOpen={() => go(WORKBENCH)}
          onLogin={() => go(LOGIN)}
          onLogout={handleLogout}
          username={auth?.username ?? null}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      </div>
      <div hidden={route !== WORKBENCH}>
        <App command={command} onHome={() => go(HOME)} onUsage={() => go(USAGE)}
          onLogin={() => go(LOGIN)} username={auth?.username ?? null} token={auth?.token}
          onOpenApiPlatform={() => go(API_PLATFORM)} onAssistantDraft={setAssistantDraft} />
      </div>
      <div hidden={route !== HOME && route !== WORKBENCH}>
        <AiAssistant open={assistantOpen} onOpenChange={setAssistantOpen} workbench={assistantDraft}
          token={auth?.token} variant={route === WORKBENCH ? 'workbench' : 'welcome'}
          onStart={() => { setAssistantOpen(false); go(WORKBENCH, 'focus') }}
          onSample={() => go(WORKBENCH, 'sample')}
          onOpen={() => go(route === WORKBENCH ? HOME : WORKBENCH)}
          onLocate={(id) => { setAssistantOpen(false); setAssistantTarget(id); go(WORKBENCH) }} />
      </div>
      {route === USAGE && (
        <TokenUsage onBack={() => go(WORKBENCH)} theme={theme} onToggleTheme={toggleTheme} />
      )}
      {route === API_PLATFORM && (
        <ApiPlatform
          onBack={() => go(WORKBENCH)}
          onLogin={() => go(LOGIN)}
          theme={theme}
          onToggleTheme={toggleTheme}
          token={auth?.token ?? null}
        />
      )}
      {(route === LOGIN || route === REGISTER) && (
        <AuthPage
          mode={route === REGISTER ? 'register' : 'login'}
          onModeChange={(mode) => go(mode === 'register' ? REGISTER : LOGIN)}
          onSuccess={(session) => {
            setAuth(session)
            go(WORKBENCH)
          }}
          onBack={() => go(HOME)}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      )}
    </>
  )
}

createRoot(container).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)

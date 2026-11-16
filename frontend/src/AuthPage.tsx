import { useEffect, useRef, useState } from 'react'
import ThemeToggle from './components/ThemeToggle'
import BrandMark from './components/BrandMark'
import { loginAccount, registerAccount, requestEmailCode } from './auth'
import type { AuthSession } from './auth'
import type { Theme } from './theme'

interface AuthPageProps {
  mode: 'login' | 'register'
  onModeChange: (mode: 'login' | 'register') => void
  /** 登录/注册成功：带着会话回工作台 */
  onSuccess: (session: AuthSession) => void
  /** 回到欢迎页 */
  onBack: () => void
  theme: Theme
  onToggleTheme: () => void
}

const USERNAME_LIMITS = '2–24 位'
const PASSWORD_LIMITS = '6–64 位'

/* ---------- 精美内联矢量图标 ---------- */

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8.2" r="3.6" />
      <path d="M5.2 19.4c.8-3.4 3.5-5.2 6.8-5.2s6 1.8 6.8 5.2" />
    </svg>
  )
}

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3.5" y="5.5" width="17" height="13" rx="2" />
      <path d="m4 7 8 6 8-6" />
    </svg>
  )
}

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4.5" y="10.5" width="15" height="10" rx="2.5" />
      <path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7" />
      <circle cx="12" cy="15.2" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  )
}

function ShieldCheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3.5 5 6v5.8c0 4.5 3 8 7 9.5 4-1.5 7-5 7-9.5V6l-7-2.5Z" />
      <path d="m9.5 11.8 1.8 1.8 3.5-3.8" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12.5 4.5 4.5 9.5-10" />
    </svg>
  )
}

function EyeIcon({ off }: { off?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 12c1.8-4.5 5.5-7.5 9.5-7.5s7.7 3 9.5 7.5c-1.8 4.5-5.5 7.5-9.5 7.5S4.3 16.5 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
      {off && <path d="M4 4l16 16" />}
    </svg>
  )
}

function ArrowRightIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  )
}

function BackArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 12H5" />
      <path d="m11 18-6-6 6-6" />
    </svg>
  )
}

/* ---------- 密码强度判断 ---------- */

function judgePassword(pw: string): { level: 0 | 1 | 2 | 3; label: string } {
  if (!pw) return { level: 0, label: '' }
  let score = 0
  if (pw.length >= 6) score += 1
  if (pw.length >= 10 || /[^A-Za-z0-9]/.test(pw)) score += 1
  if (/[A-Za-z]/.test(pw) && /\d/.test(pw)) score += 1
  const level = Math.min(3, Math.max(1, score)) as 1 | 2 | 3
  return { level, label: level === 1 ? '偏弱' : level === 2 ? '一般' : '很稳' }
}

export default function AuthPage({ mode, onModeChange, onSuccess, onBack, theme, onToggleTheme }: AuthPageProps) {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [sendingCode, setSendingCode] = useState(false)
  const [cooldown, setCooldown] = useState(0)
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const firstFieldRef = useRef<HTMLInputElement>(null)

  // 模式切换时清空提示并聚焦首个输入框
  useEffect(() => {
    setError('')
    setEmail('')
    setCode('')
    setConfirm('')
    setShowPassword(false)
    firstFieldRef.current?.focus()
  }, [mode])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const sendCode = async () => {
    if (!emailOk || sendingCode || cooldown > 0) return
    setError('')
    setSendingCode(true)
    try {
      await requestEmailCode(email.trim())
      setCooldown(60)
    } catch (requestError) {
      setError((requestError as Error).message || '验证码没有发出去，请稍后再试。')
    } finally {
      setSendingCode(false)
    }
  }

  const switchMode = (next: 'login' | 'register') => {
    if (!busy && next !== mode) onModeChange(next)
  }

  // 实时校验状态
  const nameOk = username.trim().length >= 2 && username.trim().length <= 24
  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) && email.trim().length <= 254
  const codeOk = /^\d{6}$/.test(code.trim())
  const pwOk = password.length >= 6 && password.length <= 64
  const confirmOk = mode === 'register' && confirm.length > 0 && confirm === password
  const strength = judgePassword(password)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    setError('')

    const name = username.trim()
    if (name.length < 2 || name.length > 24) {
      setError(`用户名需要 ${USERNAME_LIMITS}，中文、字母、数字都可以。`)
      return
    }
    if (mode === 'register' && !emailOk) {
      setError('请填写有效的邮箱，例如 name@example.com。')
      return
    }
    if (mode === 'register' && !codeOk) {
      setError('请填写邮箱收到的 6 位验证码。')
      return
    }
    if (password.length < 6 || password.length > 64) {
      setError(`密码需要 ${PASSWORD_LIMITS}。`)
      return
    }
    if (mode === 'register' && password !== confirm) {
      setError('两次输入的密码不一致，请再核对一遍。')
      return
    }

    setBusy(true)
    try {
      const session = mode === 'register'
        ? await registerAccount(name, password, email.trim(), code.trim())
        : await loginAccount(name, password)
      onSuccess(session)
    } catch (requestError) {
      setError((requestError as Error).message || '请求失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app auth-app">
      {/* 顶部导航 */}
      <header className="auth-bar">
        <a
          className="auth-brand"
          href="/"
          onClick={(event) => {
            event.preventDefault()
            onBack()
          }}
          title="返回欢迎页"
          data-testid="auth-back-home"
        >
          <BrandMark size={30} />
          <span className="auth-brand-name">ERFlow</span>
        </a>
        <div className="auth-bar-right">
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <button type="button" className="auth-back-link" onClick={onBack} data-testid="auth-back">
            <BackArrowIcon />
            <span>返回首页</span>
          </button>
        </div>
      </header>

      {/* 主体双栏布局 */}
      <main className="auth-main">
        <div className="auth-layout">
          {/* 左侧：精美表单卡片 */}
          <section className={'auth-sheet' + (mode === 'login' ? ' is-login' : '')}>
            <form className="auth-form" onSubmit={submit} noValidate>
              <div className="auth-form-head">
                <h2>{mode === 'login' ? '登录 ERFlow' : '注册新账号'}</h2>
                <p className="auth-sub">
                  {mode === 'login'
                    ? '用同一个账号继续你的图，出图记录都在这台服务上。'
                    : '验证码会发到邮箱，填对之后直接进入工作台。'}
                </p>
              </div>

              {/* 用户名输入框 */}
              <label className="auth-field">
                <span className="auth-label-row">
                  <span className="auth-label">用户名</span>
                  <span className="auth-label-hint">2–24 位</span>
                </span>
                <span className={'auth-input' + (nameOk ? ' is-ok' : '')}>
                  <span className="auth-input-icon"><UserIcon /></span>
                  <input
                    ref={firstFieldRef}
                    type="text"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    autoComplete="username"
                    placeholder="请输入你的用户名"
                    data-testid="auth-username"
                    maxLength={24}
                    autoFocus
                  />
                  {nameOk && <span className="auth-input-ok"><CheckIcon /></span>}
                </span>
              </label>

              {mode === 'register' && (
                <label className="auth-field">
                  <span className="auth-label-row">
                    <span className="auth-label">邮箱</span>
                  </span>
                  <span className={'auth-input' + (emailOk ? ' is-ok' : '')}>
                    <span className="auth-input-icon"><MailIcon /></span>
                    <input
                      type="email"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      autoComplete="email"
                      placeholder="name@example.com"
                      data-testid="auth-email"
                      maxLength={254}
                    />
                    {emailOk && <span className="auth-input-ok"><CheckIcon /></span>}
                  </span>
                </label>
              )}

              {mode === 'register' && (
                <label className="auth-field">
                  <span className="auth-label-row">
                    <span className="auth-label">验证码</span>
                  </span>
                  <span className="auth-code-line">
                    <span className={'auth-input' + (codeOk ? ' is-ok' : '')}>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={code}
                        onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                        autoComplete="one-time-code"
                        placeholder="6 位验证码"
                        data-testid="auth-code"
                        maxLength={6}
                      />
                    </span>
                    <button
                      type="button"
                      className="btn auth-code-send"
                      onClick={sendCode}
                      disabled={!emailOk || sendingCode || cooldown > 0}
                      data-testid="auth-send-code"
                    >
                      {sendingCode ? '发送中…' : cooldown > 0 ? `${cooldown} 秒` : '获取验证码'}
                    </button>
                  </span>
                </label>
              )}

              {/* 密码输入框 */}
              <label className="auth-field">
                <span className="auth-label-row">
                  <span className="auth-label">密码</span>
                  <span className="auth-label-hint">至少 6 位</span>
                </span>
                <span className={'auth-input' + (pwOk ? ' is-ok' : '')}>
                  <span className="auth-input-icon"><LockIcon /></span>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                    placeholder="请输入密码"
                    data-testid="auth-password"
                    maxLength={64}
                  />
                  <button
                    type="button"
                    className="auth-eye"
                    onClick={() => setShowPassword((value) => !value)}
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}
                    data-testid="auth-toggle-password"
                  >
                    <EyeIcon off={showPassword} />
                  </button>
                  {pwOk && <span className="auth-input-ok"><CheckIcon /></span>}
                </span>
              </label>

              {/* 注册确认密码 */}
              {mode === 'register' && (
                <>
                  <label className="auth-field">
                    <span className="auth-label-row">
                      <span className="auth-label">确认密码</span>
                      <span className="auth-label-hint">再次核对</span>
                    </span>
                    <span className={'auth-input' + (confirmOk ? ' is-ok' : '')}>
                      <span className="auth-input-icon"><ShieldCheckIcon /></span>
                      <input
                        type={showPassword ? 'text' : 'password'}
                        value={confirm}
                        onChange={(event) => setConfirm(event.target.value)}
                        autoComplete="new-password"
                        placeholder="再输入一次密码"
                        data-testid="auth-confirm"
                        maxLength={64}
                      />
                      <button
                        type="button"
                        className="auth-eye"
                        onClick={() => setShowPassword((value) => !value)}
                        aria-label={showPassword ? '隐藏密码' : '显示密码'}
                      >
                        <EyeIcon off={showPassword} />
                      </button>
                      {confirmOk && <span className="auth-input-ok"><CheckIcon /></span>}
                    </span>
                  </label>

                  <div className="auth-strength" data-level={strength.level} aria-live="polite">
                    <span className="auth-strength-bars" aria-hidden="true"><i /><i /><i /></span>
                    <span className="auth-strength-text">
                      {strength.level === 0 ? '建议混合字母和数字' : `密码强度：${strength.label}`}
                    </span>
                  </div>
                </>
              )}

              {/* 错误提示 */}
              {error && (
                <div className="auth-error" role="alert" data-testid="auth-error" key={error}>
                  <span className="auth-error-dot" aria-hidden="true" />
                  <span>{error}</span>
                </div>
              )}

              {/* 提交按钮 */}
              <button type="submit" className="btn btn-primary auth-submit" disabled={busy} data-testid="auth-submit">
                {busy ? (
                  <>
                    <span className="auth-spinner" aria-hidden="true" />
                    <span>正在验证…</span>
                  </>
                ) : (
                  <>
                    <span>{mode === 'login' ? '登录' : '注册并登录'}</span>
                    <ArrowRightIcon />
                  </>
                )}
              </button>
            </form>

            {/* 底部切换入口与安全说明 */}
            <div className="auth-sheet-foot">
              <p className="auth-switch">
                {mode === 'login' ? (
                  <>
                    还没有账号？
                    <button type="button" className="auth-switch-btn" disabled={busy} onClick={() => switchMode('register')} data-testid="auth-to-register">
                      注册一个
                    </button>
                  </>
                ) : (
                  <>
                    已经有账号了？
                    <button type="button" className="auth-switch-btn" disabled={busy} onClick={() => switchMode('login')} data-testid="auth-to-login">
                      直接登录
                    </button>
                  </>
                )}
              </p>
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

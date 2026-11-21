/**
 * 登录注册的客户端：请求 /api/auth/*，token 存 localStorage。
 * 与 api.ts 同一套错误口径——消息直接面向中文用户，可原样展示。
 */

export interface AuthSession {
  token: string
  username: string
}

const STORAGE_KEY = 'erflow-auth'
const REQUEST_TIMEOUT_MS = 15_000

class AuthHttpError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export function loadSession(): AuthSession | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthSession
    if (typeof parsed.token === 'string' && typeof parsed.username === 'string') return parsed
  } catch {
    /* 损坏的存储当作未登录处理 */
  }
  return null
}

function saveSession(session: AuthSession): void {
  const previous = loadSession()
  if (previous && previous.token !== session.token) {
    window.sessionStorage.removeItem('erflow-channels:' + previous.username)
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
}

export function clearSession(session: AuthSession): void {
  if (loadSession()?.token === session.token) {
    window.sessionStorage.removeItem('erflow-channels:' + session.username)
    window.localStorage.removeItem(STORAGE_KEY)
  }
}

// Logout/account switches in another tab must clear this tab's old credentials too.
window.addEventListener('storage', (event) => {
  if (event.key !== STORAGE_KEY && event.key !== null) return
  if (!event.oldValue || event.key === null) {
    for (const key of Object.keys(window.sessionStorage)) {
      if (key.startsWith('erflow-channels:')) window.sessionStorage.removeItem(key)
    }
    return
  }
  try {
    const old = JSON.parse(event.oldValue) as AuthSession
    if (typeof old.username === 'string' && loadSession()?.token !== old.token) {
      window.sessionStorage.removeItem('erflow-channels:' + old.username)
    }
  } catch { /* Ignore malformed old sessions. */ }
})

/** FastAPI 的 422 校验错误数组转成一句话 */
function validationText(detail: unknown, fallback: string): string {
  if (!Array.isArray(detail)) return fallback
  const parts = detail
    .map((item) => {
      if (item && typeof item === 'object') {
        const entry = item as { loc?: unknown; msg?: unknown }
        const field = Array.isArray(entry.loc) ? entry.loc[entry.loc.length - 1] : ''
        const label = field === 'username' ? '用户名' : field === 'password' ? '密码' : field === 'email' ? '邮箱' : String(field)
        const msg = typeof entry.msg === 'string' ? entry.msg : ''
        return msg.includes('short') ? `${label}太短` : msg.includes('long') ? `${label}太长` : msg
      }
      return ''
    })
    .filter(Boolean)
  return parts.length ? `${parts.join('；')}。${fallback}` : fallback
}

function detailText(data: unknown): string | null {
  if (data && typeof data === 'object') {
    const detail = (data as { detail?: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) return detail.trim()
  }
  return null
}

async function authFetch(path: string, init?: RequestInit): Promise<unknown> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      ...init,
    })
    const raw = await response.text()
    let data: unknown = null
    if (raw.trim()) {
      try {
        data = JSON.parse(raw)
      } catch {
        data = null
      }
    }
    if (!response.ok) {
      const hint = detailText(data)
      if (response.status === 409) throw new Error(hint || '这个用户名已被注册，换一个试试')
      if (response.status === 401) throw new AuthHttpError(hint || '用户名或密码不正确', response.status)
      if (response.status === 422) {
        throw new Error(hint || validationText(data && (data as { detail?: unknown }).detail, '请检查用户名（2–24 位）、邮箱和密码（6–64 位）'))
      }
      if (response.status >= 500) throw new Error(hint || `服务暂时不可用（HTTP ${response.status}），请稍后重试`)
      throw new Error(hint || `请求失败（HTTP ${response.status}）`)
    }
    return data
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw new Error('请求超时，请稍后重试')
    if (error instanceof TypeError) throw new Error('连不上后端服务，请确认 uvicorn 已在 127.0.0.1:8000 运行')
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

export async function requestEmailCode(email: string): Promise<void> {
  await authFetch('/api/auth/email-code', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export async function registerAccount(username: string, password: string, email: string, code: string): Promise<AuthSession> {
  const data = (await authFetch('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password, email, code }),
  })) as Partial<AuthSession> | null
  // 兼容尚未更新的本地后端，旧注册接口只返回用户名。
  return data?.username && data.token === undefined ? loginAccount(username, password) : acceptSession(data)
}

export async function loginAccount(username: string, password: string): Promise<AuthSession> {
  const data = (await authFetch('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })) as Partial<AuthSession> | null
  return acceptSession(data)
}

function acceptSession(data: Partial<AuthSession> | null): AuthSession {
  if (!data || typeof data.token !== 'string' || !data.token || typeof data.username !== 'string' || !data.username) {
    throw new Error('后端返回的数据不完整，请检查后端版本。')
  }
  const session = { token: data.token, username: data.username }
  saveSession(session)
  return session
}

/** null 表示这次没能完成校验，等待服务恢复后可再次核对。 */
export async function verifySession(session: AuthSession): Promise<boolean | null> {
  try {
    const data = (await authFetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${session.token}` },
    })) as Partial<AuthSession> | null
    return typeof data?.username === 'string' ? data.username === session.username : null
  } catch (error) {
    return error instanceof AuthHttpError && error.status === 401 ? false : null
  }
}

export async function logoutSession(session: AuthSession): Promise<void> {
  clearSession(session)
  try {
    await authFetch('/api/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ token: session.token }),
    })
  } catch {
    /* 后端删不删都无所谓：本地已退出，token 自然过期 */
  }
}

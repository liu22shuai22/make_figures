/** Channels belong to an account in this browser tab and expire when the tab session ends. */
import { loadSession } from './auth'

interface BrowserProvider {
  id: string
  [key: string]: unknown
}

interface BrowserStore {
  active_id: string | null
  providers: BrowserProvider[]
}

function storageKey(token: string) {
  const session = loadSession()
  if (!session || session.token !== token) throw new Error('请先登录')
  return 'erflow-channels:' + session.username
}

function readStore(token: string): BrowserStore {
  const raw = sessionStorage.getItem(storageKey(token))
  if (!raw) return { active_id: null, providers: [] }
  const store = JSON.parse(raw) as BrowserStore
  if (!Array.isArray(store.providers)) throw new Error('本地渠道配置无效，请重新导入')
  return store
}

export function channelHeaders(token?: string, all = false): Record<string, string> {
  if (!token) return {}
  const stored = readStore(token)
  const store = all ? stored : {
    active_id: stored.active_id,
    providers: stored.providers.filter(item => item.id === stored.active_id),
  }
  const bytes = new TextEncoder().encode(JSON.stringify(store))
  const encoded = btoa(Array.from(bytes, value => String.fromCharCode(value)).join(''))
  if (encoded.length > 32_000) throw new Error('渠道配置过大，请减少保存的渠道')
  return { 'X-ERFlow-Providers': encoded }
}

export function saveBrowserChannels(token: string, payload: unknown) {
  if (!payload || typeof payload !== 'object' || !('browser_store' in payload)) return
  const store = (payload as { browser_store: BrowserStore }).browser_store
  if (!store || !Array.isArray(store.providers)) throw new Error('渠道返回格式无效')
  sessionStorage.setItem(storageKey(token), JSON.stringify(store))
}

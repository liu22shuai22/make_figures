import { channelHeaders, saveBrowserChannels } from './channelSession'
/** API 平台：New API 风格多模型渠道接入 */

export interface ProviderPreset {
  id: string
  name: string
  kind: 'openai' | 'anthropic'
  base_url: string
  model: string
  hint: string
  default_key: string
}

export interface ProviderPublic {
  id: string
  name: string
  kind: 'openai' | 'anthropic'
  base_url: string
  api_key_masked: string
  has_key: boolean
  model: string
  preset: string
  ready: boolean
}

export interface ProvidersPayload {
  active_id: string | null
  providers: ProviderPublic[]
  presets: ProviderPreset[]
}

export interface ModelOption {
  id: string
  display_name: string
  owned_by?: string
}

async function readJson(response: Response) {
  const text = await response.text()
  try {
    return text ? JSON.parse(text) : null
  } catch {
    return null
  }
}

function detailMessage(data: unknown, fallback: string) {
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return fallback
}

async function authFetch(path: string, token: string, init?: RequestInit) {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...channelHeaders(token, true),
      Authorization: `Bearer ${token}`,
      ...(init?.headers || {}),
    },
  })
  const data = await readJson(response)
  if (response.ok) saveBrowserChannels(token, data)
  return { response, data }
}

export async function fetchProviders(token: string): Promise<ProvidersPayload> {
  const { response, data } = await authFetch('/api/providers', token, { method: 'GET' })
  if (!response.ok) throw new Error(detailMessage(data, '无法读取渠道列表'))
  return data as ProvidersPayload
}

export type ProviderBundle = {
  format: string
  version: number
  exported_at?: string
  include_secrets?: boolean
  active_id?: string | null
  providers: Array<{
    id?: string
    name: string
    kind: 'openai' | 'anthropic'
    base_url: string
    model: string
    preset: string
    api_key?: string
    has_key?: boolean
  }>
}

export async function exportProviders(token: string, secrets = false): Promise<ProviderBundle> {
  const { response, data } = await authFetch(
    `/api/providers/export?secrets=${secrets ? 'true' : 'false'}`,
    token,
    { method: 'GET' },
  )
  if (!response.ok) throw new Error(detailMessage(data, '导出渠道失败'))
  return data as ProviderBundle
}

export async function importProviders(
  token: string,
  bundle: ProviderBundle | Record<string, unknown>,
  mode: 'merge' | 'replace' = 'merge',
): Promise<ProvidersPayload> {
  const { response, data } = await authFetch('/api/providers/import', token, {
    method: 'POST',
    body: JSON.stringify({ bundle, mode }),
  })
  if (!response.ok) throw new Error(detailMessage(data, '导入渠道失败'))
  return data as ProvidersPayload
}

export async function saveProvider(
  token: string,
  body: {
    id?: string
    name: string
    kind: 'openai' | 'anthropic'
    base_url: string
    api_key: string
    model: string
    preset: string
    activate?: boolean
  },
): Promise<ProvidersPayload> {
  const { response, data } = await authFetch('/api/providers', token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(detailMessage(data, '保存渠道失败'))
  return data as ProvidersPayload
}

export async function activateProvider(token: string, id: string): Promise<ProvidersPayload> {
  const { response, data } = await authFetch('/api/providers/active', token, {
    method: 'PUT',
    body: JSON.stringify({ id }),
  })
  if (!response.ok) throw new Error(detailMessage(data, '切换渠道失败'))
  return data as ProvidersPayload
}

export async function removeProvider(token: string, id: string): Promise<ProvidersPayload> {
  const { response, data } = await authFetch(`/api/providers/${encodeURIComponent(id)}`, token, {
    method: 'DELETE',
  })
  if (!response.ok) throw new Error(detailMessage(data, '删除渠道失败'))
  return data as ProvidersPayload
}

export async function probeGateway(
  token: string,
  body: { base_url: string; api_key?: string; id?: string },
): Promise<{ ok: boolean; models: ModelOption[]; error: string | null; base_url: string; hello: unknown }> {
  const { response, data } = await authFetch('/api/providers/probe-gateway', token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(detailMessage(data, '探测网关失败'))
  return data as { ok: boolean; models: ModelOption[]; error: string | null; base_url: string; hello: unknown }
}

export async function listRemoteModels(
  token: string,
  body: { base_url: string; api_key: string; id?: string },
): Promise<ModelOption[]> {
  const { response, data } = await authFetch('/api/providers/list-models', token, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(detailMessage(data, '拉取模型列表失败'))
  const models = (data as { models?: ModelOption[] })?.models
  return Array.isArray(models) ? models : []
}

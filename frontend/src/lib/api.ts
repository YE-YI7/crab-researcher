/**
 * CrabRes API 层
 * 
 * 自动重试 + Render 冷启动友好处理
 */

const API = import.meta.env.VITE_API_BASE || '/api'

// Token 管理
export function getToken(): string | null { return localStorage.getItem('crabres_token') }
export function setToken(token: string) { localStorage.setItem('crabres_token', token) }
export function clearToken() { localStorage.removeItem('crabres_token') }

class ApiResponseError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiResponseError'
  }
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map(item => typeof item?.msg === 'string' ? item.msg : '')
      .filter(Boolean)
      .join('; ') || fallback
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message)
  }
  return fallback
}

let _onAuthExpired: (() => void) | null = null
export function setAuthExpiredHandler(fn: () => void) { _onAuthExpired = fn }

// 冷启动状态回调（让 UI 显示提示）
let _onColdStart: ((waking: boolean) => void) | null = null
export function setColdStartHandler(fn: (waking: boolean) => void) { _onColdStart = fn }

/**
 * 带自动重试的 API 请求
 * - 网络错误（Render 冷启动）自动重试 3 次，指数退避
 * - 触发冷启动提示让用户知道在等什么
 */
export async function api<T = any>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts?.headers as Record<string, string> || {}),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const maxRetries = 3
  let lastError: Error | null = null

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      if (attempt > 0) {
        // 指数退避：2s, 5s, 10s
        const delay = Math.min(2000 * Math.pow(2, attempt - 1), 10000)
        _onColdStart?.(true)
        await new Promise(r => setTimeout(r, delay))
      }

      const res = await fetch(`${API}${path}`, { ...opts, headers })
      
      // 成功了，清除冷启动提示
      if (attempt > 0) _onColdStart?.(false)

      if (res.status === 401) {
        clearToken()
        _onAuthExpired?.()
        throw new ApiResponseError(401, 'Session expired')
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new ApiResponseError(
          res.status,
          errorMessage(err.detail, `Request failed (${res.status})`),
        )
      }
      const text = await res.text()
      return text ? JSON.parse(text) : ({} as T)
    } catch (e: any) {
      lastError = e
      // 只对网络错误（冷启动）重试，业务错误不重试
      if (e instanceof ApiResponseError) {
        _onColdStart?.(false)
        throw e
      }
      // 最后一次重试也失败了
      if (attempt === maxRetries) {
        _onColdStart?.(false)
        throw new Error('Server is starting up. Please try again in a moment.')
      }
    }
  }

  throw lastError || new Error('Unknown error')
}

/** Fetch an authenticated binary asset and expose it as a temporary browser URL. */
export async function apiBlobUrl(path: string): Promise<string> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${API}${path}`, { headers })
  if (res.status === 401) {
    clearToken()
    _onAuthExpired?.()
    throw new ApiResponseError(401, 'Session expired')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiResponseError(
      res.status,
      errorMessage(err.detail, `Request failed (${res.status})`),
    )
  }
  return URL.createObjectURL(await res.blob())
}

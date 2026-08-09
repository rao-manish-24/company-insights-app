import { getAuthToken } from './auth'
import { API_BASE, REQUEST_TIMEOUT_MS } from './config'
import type {
  AnalysisListItem,
  AuthResponse,
  CompanyAnalysis,
  CompanyResolution,
  CompanySuggestion,
  ExpandInsightKind,
  ExpandInsightResult,
  UserPublic,
} from './types'

export class ApiError extends Error {
  status: number
  cancelled: boolean

  constructor(message: string, status: number, options?: { cancelled?: boolean }) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.cancelled = Boolean(options?.cancelled)
  }
}

function parseDetail(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') {
        const row = item as { msg?: unknown; type?: unknown; loc?: unknown }
        const loc = Array.isArray(row.loc) ? row.loc.map(String) : []
        if (loc.includes('company_name') || row.type === 'string_too_short') {
          return 'Not a valid company name. Enter a real company (for example Microsoft or Nestlé).'
        }
        if (typeof row.msg === 'string') return row.msg
      }
      return JSON.stringify(item)
    })
    return messages.join('; ')
  }
  return null
}

async function request<T>(
  path: string,
  init?: RequestInit & { auth?: boolean },
): Promise<T> {
  const controller = new AbortController()
  const { auth = false, signal: userSignal, ...fetchInit } = init || {}
  const onUserAbort = () => controller.abort()
  if (userSignal) {
    if (userSignal.aborted) controller.abort()
    else userSignal.addEventListener('abort', onUserAbort, { once: true })
  }
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(fetchInit.body ? { 'Content-Type': 'application/json' } : {}),
    ...((fetchInit.headers as Record<string, string>) || {}),
  }
  if (auth) {
    const token = getAuthToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...fetchInit,
      signal: controller.signal,
      headers,
    })

    if (!response.ok) {
      let message = `Request failed (${response.status})`
      try {
        const body = await response.json()
        message = parseDetail(body) || message
      } catch {
        // ignore parse errors
      }
      throw new ApiError(message, response.status)
    }

    return response.json() as Promise<T>
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof DOMException && err.name === 'AbortError') {
      if (userSignal?.aborted) {
        throw new ApiError('Search stopped.', 499, { cancelled: true })
      }
      throw new ApiError('Request timed out. Please try again.', 408)
    }
    throw new ApiError(
      err instanceof Error ? err.message : 'Network request failed',
      0,
    )
  } finally {
    window.clearTimeout(timeout)
    userSignal?.removeEventListener('abort', onUserAbort)
  }
}

export function registerAccount(payload: {
  email: string
  password: string
  display_name?: string
}): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function loginAccount(payload: {
  email: string
  password: string
}): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function startGuestSession(): Promise<AuthResponse> {
  return request<AuthResponse>('/auth/guest', {
    method: 'POST',
  })
}

export function fetchMe(): Promise<UserPublic> {
  return request<UserPublic>('/auth/me', { auth: true })
}

export function resolveCompany(
  query: string,
  options?: { signal?: AbortSignal },
): Promise<CompanyResolution> {
  return request<CompanyResolution>('/companies/resolve', {
    method: 'POST',
    auth: true,
    body: JSON.stringify({ query }),
    signal: options?.signal,
  })
}

export async function suggestCompanies(query: string): Promise<CompanySuggestion[]> {
  const q = query.trim()
  if (q.length < 2) return []
  const result = await request<{ query: string; suggestions: CompanySuggestion[] }>(
    `/companies/suggest?q=${encodeURIComponent(q)}`,
  )
  return result.suggestions || []
}

export function analyzeCompany(
  companyName: string,
  forceRefresh = false,
  options?: { confirmed?: boolean; signal?: AbortSignal },
): Promise<CompanyAnalysis> {
  return request<CompanyAnalysis>('/analyze', {
    method: 'POST',
    auth: true,
    body: JSON.stringify({
      company_name: companyName,
      force_refresh: forceRefresh,
      confirmed: Boolean(options?.confirmed),
    }),
    signal: options?.signal,
  })
}

export function listRecentAnalyses(limit = 15): Promise<AnalysisListItem[]> {
  return request<AnalysisListItem[]>(`/analyses?limit=${limit}`, { auth: true })
}

export function clearAnalysesHistory(): Promise<{ status: string; deleted: number }> {
  return request<{ status: string; deleted: number }>('/analyses', {
    method: 'DELETE',
    auth: true,
  })
}

export function getAnalysis(
  id: number,
  options?: { signal?: AbortSignal },
): Promise<CompanyAnalysis> {
  return request<CompanyAnalysis>(`/analyses/${id}`, {
    auth: true,
    signal: options?.signal,
  })
}

export interface EmailBriefResult {
  status: string
  to: string
  analysis_id: number
  company_name: string
}

export function emailAnalysis(id: number, to?: string): Promise<EmailBriefResult> {
  return request<EmailBriefResult>(`/analyses/${id}/email`, {
    method: 'POST',
    auth: true,
    body: JSON.stringify(to ? { to } : {}),
  })
}

export function expandInsight(
  analysisId: number,
  kind: ExpandInsightKind,
  index: number,
  options?: { depth?: 'standard' | 'deep'; priorAnalysis?: string },
): Promise<ExpandInsightResult> {
  return request<ExpandInsightResult>(`/analyses/${analysisId}/expand`, {
    method: 'POST',
    auth: true,
    body: JSON.stringify({
      kind,
      index,
      depth: options?.depth || 'standard',
      prior_analysis: options?.priorAnalysis || undefined,
    }),
  })
}

import { API_BASE, REQUEST_TIMEOUT_MS } from './config'
import type {
  AnalysisListItem,
  CompanyAnalysis,
  ExpandInsightKind,
  ExpandInsightResult,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function parseDetail(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg)
        }
        return JSON.stringify(item)
      })
      .join('; ')
  }
  return null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: init?.signal ?? controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init?.headers || {}),
      },
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
      throw new ApiError('Request timed out. Please try again.', 408)
    }
    throw new ApiError(
      err instanceof Error ? err.message : 'Network request failed',
      0,
    )
  } finally {
    window.clearTimeout(timeout)
  }
}

export function analyzeCompany(companyName: string, forceRefresh = false): Promise<CompanyAnalysis> {
  return request<CompanyAnalysis>('/analyze', {
    method: 'POST',
    body: JSON.stringify({
      company_name: companyName,
      force_refresh: forceRefresh,
    }),
  })
}

export function listRecentAnalyses(limit = 15): Promise<AnalysisListItem[]> {
  return request<AnalysisListItem[]>(`/analyses?limit=${limit}`)
}

export function clearAnalysesHistory(): Promise<{ status: string; deleted: number }> {
  return request<{ status: string; deleted: number }>('/analyses', {
    method: 'DELETE',
  })
}

export function getAnalysis(id: number): Promise<CompanyAnalysis> {
  return request<CompanyAnalysis>(`/analyses/${id}`)
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
    body: JSON.stringify({
      kind,
      index,
      depth: options?.depth || 'standard',
      prior_analysis: options?.priorAnalysis || undefined,
    }),
  })
}

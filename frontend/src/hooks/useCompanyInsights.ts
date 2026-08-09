import { useCallback, useEffect, useRef, useState, useTransition } from 'react'
import { analyzeCompany, clearAnalysesHistory, getAnalysis, listRecentAnalyses } from '../api'
import { ApiError } from '../api'
import type { AnalysisListItem, AnalysisRunMetrics, CompanyAnalysis } from '../types'
import { useAuth } from './useAuth'

const HISTORY_LIMIT = 15

export function useCompanyInsights() {
  const { user, openAuth, pendingCompany, clearPendingCompany } = useAuth()
  const [query, setQuery] = useState('')
  const [analysis, setAnalysis] = useState<CompanyAnalysis | null>(null)
  const [recent, setRecent] = useState<AnalysisListItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMode, setLoadingMode] = useState<'analyze' | 'open'>('analyze')
  const [runMetrics, setRunMetrics] = useState<AnalysisRunMetrics | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [, startTransition] = useTransition()
  const requestIdRef = useRef(0)

  const handleAuthError = useCallback(
    (err: unknown, pending?: string) => {
      if (err instanceof ApiError && err.status === 401) {
        openAuth({
          mode: 'signin',
          message: 'Sign in to generate insights and access your library.',
          pendingCompany: pending,
        })
        return true
      }
      return false
    },
    [openAuth],
  )

  const loadHistory = useCallback(async () => {
    if (!user) {
      openAuth({
        mode: 'signin',
        message: 'Sign in to load your private library.',
      })
      return
    }
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const items = await listRecentAnalyses(HISTORY_LIMIT)
      startTransition(() => setRecent(items))
      setHistoryLoaded(true)
    } catch (err) {
      if (handleAuthError(err)) return
      setHistoryError(err instanceof Error ? err.message : 'Could not load history')
    } finally {
      setHistoryLoading(false)
    }
  }, [user, openAuth, handleAuthError, startTransition])

  const clearHistory = useCallback(async () => {
    if (!user) {
      openAuth({
        mode: 'signin',
        message: 'Sign in to manage your library.',
      })
      return
    }
    const confirmed = window.confirm(
      'Clear all saved briefs from your library? This cannot be undone.',
    )
    if (!confirmed) return

    setHistoryLoading(true)
    setHistoryError(null)
    try {
      await clearAnalysesHistory()
      startTransition(() => {
        setRecent([])
        setAnalysis(null)
        setRunMetrics(null)
      })
      setHistoryLoaded(true)
    } catch (err) {
      if (handleAuthError(err)) return
      setHistoryError(err instanceof Error ? err.message : 'Could not clear history')
    } finally {
      setHistoryLoading(false)
    }
  }, [user, openAuth, handleAuthError, startTransition])

  const runAnalysis = useCallback(
    async (companyName: string, forceRefresh = false) => {
      const trimmed = companyName.trim()
      if (!trimmed) {
        setError('Enter a company name to generate an insights brief.')
        return
      }

      if (!user) {
        openAuth({
          mode: 'signin',
          message: 'Sign in to generate insights for this company.',
          pendingCompany: trimmed,
        })
        return
      }

      const requestId = ++requestIdRef.current
      const started = performance.now()
      setLoading(true)
      setLoadingMode('analyze')
      setRunMetrics(null)
      setError(null)

      try {
        const result = await analyzeCompany(trimmed, forceRefresh)
        if (requestId !== requestIdRef.current) return
        const clientElapsed = performance.now() - started
        setAnalysis(result)
        setQuery(result.company_name)
        setRunMetrics({
          elapsedMs: result.cached ? clientElapsed : (result.elapsed_ms ?? clientElapsed),
          promptTokens: result.prompt_tokens ?? null,
          completionTokens: result.completion_tokens ?? null,
          totalTokens: result.total_tokens ?? null,
          cached: Boolean(result.cached),
        })
        await loadHistory()
      } catch (err) {
        if (requestId !== requestIdRef.current) return
        if (handleAuthError(err, trimmed)) {
          setError(null)
          return
        }
        setError(err instanceof Error ? err.message : 'Analysis failed')
        setRunMetrics(null)
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false)
        }
      }
    },
    [user, openAuth, loadHistory, handleAuthError],
  )

  // After successful sign-in/register, continue the company the guest typed.
  useEffect(() => {
    if (!user || !pendingCompany) return
    const company = pendingCompany
    clearPendingCompany()
    setQuery(company)
    void runAnalysis(company)
  }, [user, pendingCompany, clearPendingCompany, runAnalysis])

  // Reset workspace when the account changes / signs out.
  useEffect(() => {
    if (user) {
      void loadHistory()
      return
    }
    setAnalysis(null)
    setRecent([])
    setHistoryLoaded(false)
    setRunMetrics(null)
    setError(null)
    setHistoryError(null)
  }, [user?.id]) // eslint-disable-line react-hooks/exhaustive-deps -- intentional on identity change

  const openRecent = useCallback(
    async (id: number) => {
      if (!user) {
        openAuth({
          mode: 'signin',
          message: 'Sign in to reopen briefs from your library.',
        })
        return
      }
      const requestId = ++requestIdRef.current
      setLoading(true)
      setLoadingMode('open')
      setRunMetrics(null)
      setError(null)
      try {
        const result = await getAnalysis(id)
        if (requestId !== requestIdRef.current) return
        setAnalysis(result)
        setQuery(result.company_name)
        setRunMetrics(null)
      } catch (err) {
        if (requestId !== requestIdRef.current) return
        if (handleAuthError(err)) return
        setError(err instanceof Error ? err.message : 'Could not load analysis')
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false)
        }
      }
    },
    [user, openAuth, handleAuthError],
  )

  return {
    query,
    setQuery,
    analysis,
    recent,
    error,
    historyError,
    historyLoading,
    historyLoaded,
    loading,
    loadingMode,
    runMetrics,
    runAnalysis,
    openRecent,
    loadHistory,
    clearHistory,
  }
}

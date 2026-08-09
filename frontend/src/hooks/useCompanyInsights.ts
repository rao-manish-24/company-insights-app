import { useCallback, useRef, useState, useTransition } from 'react'
import { analyzeCompany, clearAnalysesHistory, getAnalysis, listRecentAnalyses } from '../api'
import type { AnalysisListItem, AnalysisRunMetrics, CompanyAnalysis } from '../types'

const HISTORY_LIMIT = 15

export function useCompanyInsights() {
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

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const items = await listRecentAnalyses(HISTORY_LIMIT)
      startTransition(() => setRecent(items))
      setHistoryLoaded(true)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Could not load history')
    } finally {
      setHistoryLoading(false)
    }
  }, [startTransition])

  const clearHistory = useCallback(async () => {
    const confirmed = window.confirm(
      'Clear all saved briefs from the library? This cannot be undone.',
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
      setHistoryError(err instanceof Error ? err.message : 'Could not clear history')
    } finally {
      setHistoryLoading(false)
    }
  }, [startTransition])

  const runAnalysis = useCallback(
    async (companyName: string, forceRefresh = false) => {
      const trimmed = companyName.trim()
      if (!trimmed) {
        setError('Enter a company name to generate an insights brief.')
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
          // Cache hits return ~0 server elapsed; prefer wall-clock for UX.
          elapsedMs: result.cached ? clientElapsed : (result.elapsed_ms ?? clientElapsed),
          promptTokens: result.prompt_tokens ?? null,
          completionTokens: result.completion_tokens ?? null,
          totalTokens: result.total_tokens ?? null,
          cached: Boolean(result.cached),
        })
        await loadHistory()
      } catch (err) {
        if (requestId !== requestIdRef.current) return
        setError(err instanceof Error ? err.message : 'Analysis failed')
        setRunMetrics(null)
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false)
        }
      }
    },
    [loadHistory],
  )

  const openRecent = useCallback(async (id: number) => {
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
      setError(err instanceof Error ? err.message : 'Could not load analysis')
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false)
      }
    }
  }, [])

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

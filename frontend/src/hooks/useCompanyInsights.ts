import { useCallback, useRef, useState, useTransition } from 'react'
import { analyzeCompany, clearAnalysesHistory, getAnalysis, listRecentAnalyses } from '../api'
import type { AnalysisListItem, CompanyAnalysis } from '../types'

const HISTORY_LIMIT = 15

export function useCompanyInsights() {
  const [query, setQuery] = useState('')
  const [analysis, setAnalysis] = useState<CompanyAnalysis | null>(null)
  const [recent, setRecent] = useState<AnalysisListItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
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
      setLoading(true)
      setError(null)

      try {
        const result = await analyzeCompany(trimmed, forceRefresh)
        if (requestId !== requestIdRef.current) return
        setAnalysis(result)
        setQuery(result.company_name)
        await loadHistory()
      } catch (err) {
        if (requestId !== requestIdRef.current) return
        setError(err instanceof Error ? err.message : 'Analysis failed')
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
    setError(null)
    try {
      const result = await getAnalysis(id)
      if (requestId !== requestIdRef.current) return
      setAnalysis(result)
      setQuery(result.company_name)
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
    runAnalysis,
    openRecent,
    loadHistory,
    clearHistory,
  }
}

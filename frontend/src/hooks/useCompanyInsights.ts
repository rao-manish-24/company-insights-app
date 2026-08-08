import { useCallback, useEffect, useRef, useState, useTransition } from 'react'
import { analyzeCompany, getAnalysis, listRecentAnalyses } from '../api'
import type { AnalysisListItem, CompanyAnalysis } from '../types'

export function useCompanyInsights() {
  const [query, setQuery] = useState('')
  const [analysis, setAnalysis] = useState<CompanyAnalysis | null>(null)
  const [recent, setRecent] = useState<AnalysisListItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [, startTransition] = useTransition()
  const requestIdRef = useRef(0)

  const refreshRecent = useCallback(async () => {
    try {
      const items = await listRecentAnalyses()
      startTransition(() => setRecent(items))
      setHistoryError(null)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : 'Could not load recent briefs')
    }
  }, [startTransition])

  useEffect(() => {
    void refreshRecent()
  }, [refreshRecent])

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
        await refreshRecent()
      } catch (err) {
        if (requestId !== requestIdRef.current) return
        setError(err instanceof Error ? err.message : 'Analysis failed')
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false)
        }
      }
    },
    [refreshRecent],
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
    loading,
    runAnalysis,
    openRecent,
  }
}

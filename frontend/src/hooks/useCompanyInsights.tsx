import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import {
  analyzeCompany,
  clearAnalysesHistory,
  getAnalysis,
  listRecentAnalyses,
  resolveCompany,
  suggestCompanies,
} from '../api'
import { ApiError } from '../api'
import { clearAuthToken } from '../auth'
import type {
  AnalysisListItem,
  AnalysisRunMetrics,
  CompanyAnalysis,
  CompanySuggestion,
} from '../types'
import { useAuth } from './useAuth'

const HISTORY_LIMIT = 15
const AUTOCOMPLETE_DEBOUNCE_MS = 280

/** Strong autocomplete hit that can skip a full /resolve round-trip. */
function strongAutocompleteMatch(
  query: string,
  items: CompanySuggestion[],
): CompanySuggestion | null {
  const raw = query.trim().toLowerCase()
  if (!raw || items.length === 0) return null
  const qTokens = raw.replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean)
  for (const item of items) {
    if (item.confidence < 0.92) continue
    const name = item.name.trim().toLowerCase()
    const nameTokens = name.replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean)
    // Full typed name matches suggestion tokens (Bain & Company).
    if (qTokens.length >= 2 && qTokens.join(' ') === nameTokens.join(' ')) {
      return item
    }
    if (name === raw) return item
    // Long single-token brand with high confidence (Microsoft → Microsoft Corporation).
    if (
      qTokens.length === 1 &&
      qTokens[0].length >= 5 &&
      nameTokens[0] === qTokens[0] &&
      item.confidence >= 0.97
    ) {
      return item
    }
  }
  return null
}

export type RunAnalysisResult =
  | 'analyzed'
  | 'suggestions'
  | 'error'
  | 'auth'
  | 'aborted'
  | 'invalid'

type CompanyInsightsContextValue = {
  query: string
  setQuery: (value: string) => void
  analysis: CompanyAnalysis | null
  recent: AnalysisListItem[]
  error: string | null
  suggestions: CompanySuggestion[]
  suggestionMessage: string | null
  autocomplete: CompanySuggestion[]
  autocompleteOpen: boolean
  autocompleteLoading: boolean
  activeSuggestionIndex: number
  setAutocompleteOpen: (open: boolean) => void
  setActiveSuggestionIndex: (index: number) => void
  historyError: string | null
  historyLoading: boolean
  historyLoaded: boolean
  loading: boolean
  loadingMode: 'analyze' | 'open'
  runMetrics: AnalysisRunMetrics | null
  runAnalysis: (
    companyName: string,
    forceRefresh?: boolean,
    options?: { skipResolve?: boolean; confirmed?: boolean },
  ) => Promise<RunAnalysisResult>
  cancelAnalysis: () => void
  /** Hard-stop search + wipe workspace (used by End session / Sign out). */
  endSession: () => void
  pickSuggestion: (suggestion: CompanySuggestion) => Promise<RunAnalysisResult>
  onSearchKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void
  openRecent: (id: number) => Promise<RunAnalysisResult>
  loadHistory: () => Promise<void>
  clearHistory: () => Promise<void>
  clearWorkspaceError: () => void
  clearRunMetrics: () => void
}

const CompanyInsightsContext = createContext<CompanyInsightsContextValue | null>(null)

export function CompanyInsightsProvider({ children }: { children: ReactNode }) {
  const { user, openAuth, pendingCompany, clearPendingCompany, continuePrivately } = useAuth()
  const [query, setQueryState] = useState('')
  const [analysis, setAnalysis] = useState<CompanyAnalysis | null>(null)
  const [recent, setRecent] = useState<AnalysisListItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [suggestions, setSuggestions] = useState<CompanySuggestion[]>([])
  const [suggestionMessage, setSuggestionMessage] = useState<string | null>(null)
  const [autocomplete, setAutocomplete] = useState<CompanySuggestion[]>([])
  const [autocompleteOpen, setAutocompleteOpen] = useState(false)
  const [autocompleteLoading, setAutocompleteLoading] = useState(false)
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(-1)
  const [loading, setLoading] = useState(false)
  const [loadingMode, setLoadingMode] = useState<'analyze' | 'open'>('analyze')
  const [runMetrics, setRunMetrics] = useState<AnalysisRunMetrics | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyLoaded, setHistoryLoaded] = useState(false)
  const [, startTransition] = useTransition()
  const requestIdRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const autocompleteSeqRef = useRef(0)
  /** Only fetch/open autocomplete after the user edits the search box. */
  const autocompleteLiveRef = useRef(false)

  const beginRequest = useCallback(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const requestId = ++requestIdRef.current
    return { requestId, signal: controller.signal }
  }, [])

  const cancelAnalysis = useCallback(() => {
    requestIdRef.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    setLoading(false)
    setRunMetrics(null)
    setError(null)
    setSuggestionMessage(null)
  }, [])

  const handleAuthError = useCallback(
    (err: unknown, pending?: string) => {
      if (err instanceof ApiError && err.status === 401) {
        clearAuthToken()
        openAuth({
          mode: 'signin',
          message: 'Session expired. Continue privately or sign in to keep going.',
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
      try {
        await continuePrivately()
      } catch {
        openAuth({
          mode: 'signin',
          message: 'Sign in or start a private session to load your library.',
        })
        return
      }
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
  }, [user, openAuth, continuePrivately, handleAuthError, startTransition])

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

  const clearAutocomplete = useCallback(() => {
    autocompleteLiveRef.current = false
    setAutocomplete([])
    setAutocompleteOpen(false)
    setActiveSuggestionIndex(-1)
    setAutocompleteLoading(false)
  }, [])

  const endSession = useCallback(() => {
    cancelAnalysis()
    setAnalysis(null)
    setRecent([])
    setHistoryLoaded(false)
    setHistoryLoading(false)
    setRunMetrics(null)
    setError(null)
    setHistoryError(null)
    setSuggestions([])
    setSuggestionMessage(null)
    setQueryState('')
    setLoading(false)
    setLoadingMode('analyze')
    clearAutocomplete()
  }, [cancelAnalysis, clearAutocomplete])

  const clearRunMetrics = useCallback(() => {
    setRunMetrics(null)
  }, [])

  const clearWorkspaceError = useCallback(() => {
    setError(null)
  }, [])

  const executeAnalyze = useCallback(
    async (
      companyName: string,
      forceRefresh: boolean,
      requestId: number,
      options?: {
        confirmed?: boolean
        resolved?: boolean
        ticker?: string | null
        signal?: AbortSignal
      },
    ): Promise<RunAnalysisResult> => {
      const started = performance.now()
      setLoadingMode('analyze')
      const result = await analyzeCompany(companyName, forceRefresh, {
        confirmed: options?.confirmed,
        resolved: options?.resolved,
        ticker: options?.ticker,
        signal: options?.signal,
      })
      if (requestId !== requestIdRef.current) return 'aborted'
      const clientElapsed = performance.now() - started
      setAnalysis(result)
      setQueryState(result.company_name)
      setSuggestions([])
      setSuggestionMessage(null)
      clearAutocomplete()
      setRunMetrics({
        elapsedMs: result.cached ? clientElapsed : (result.elapsed_ms ?? clientElapsed),
        promptTokens: result.prompt_tokens ?? null,
        completionTokens: result.completion_tokens ?? null,
        totalTokens: result.total_tokens ?? null,
        cached: Boolean(result.cached),
      })
      // Don't block "brief ready" on a second history RTT.
      void loadHistory()
      return 'analyzed'
    },
    [loadHistory, clearAutocomplete],
  )

  const runAnalysis = useCallback(
    async (
      companyName: string,
      forceRefresh = false,
      options?: {
        skipResolve?: boolean
        confirmed?: boolean
        ticker?: string | null
      },
    ): Promise<RunAnalysisResult> => {
      const trimmed = companyName.trim()
      if (!trimmed) {
        setError('Enter a company name to generate an insights brief.')
        setSuggestions([])
        setSuggestionMessage(null)
        return 'invalid'
      }
      if (trimmed.length < 2 || !/[A-Za-z]/.test(trimmed)) {
        setError('No valid companies found with this name.')
        setSuggestions([])
        setSuggestionMessage(null)
        return 'invalid'
      }

      if (!user) {
        try {
          await continuePrivately()
        } catch {
          openAuth({
            mode: 'signin',
            message: 'Start a private session or sign in to generate insights.',
            pendingCompany: trimmed,
          })
          return 'auth'
        }
      }

      const { requestId, signal } = beginRequest()
      setLoading(true)
      setLoadingMode('analyze')
      setRunMetrics(null)
      // Drop a prior brief on new searches so home doesn't treat stale data as success.
      // Keep the current brief visible while Refresh runs on /insights.
      if (!forceRefresh) {
        setAnalysis(null)
      }
      setError(null)
      setSuggestions([])
      setSuggestionMessage(null)
      clearAutocomplete()

      try {
        let target = trimmed
        let resolvedExact = Boolean(options?.skipResolve && options?.confirmed)
        let tickerHint = options?.ticker ?? null
        let confirmed = Boolean(options?.confirmed)

        // Reuse live autocomplete when it already has a high-confidence exact brand.
        if (!options?.skipResolve) {
          const fromAutocomplete = strongAutocompleteMatch(trimmed, autocomplete)
          if (fromAutocomplete) {
            target = fromAutocomplete.name
            resolvedExact = true
            confirmed = true
            tickerHint = fromAutocomplete.ticker ?? null
            setQueryState(target)
          }
        }

        if (!options?.skipResolve && !resolvedExact) {
          const resolution = await resolveCompany(trimmed, { signal })
          if (requestId !== requestIdRef.current) return 'aborted'

          if (resolution.status === 'not_found') {
            setError(resolution.message || 'No valid companies found with this name.')
            setSuggestions([])
            setSuggestionMessage(null)
            return 'error'
          }

          if (resolution.status === 'ambiguous') {
            setError(null)
            setSuggestionMessage(
              resolution.message ||
                `Company name “${trimmed}” does not exist as an exact match. Did you mean one of these?`,
            )
            setSuggestions(resolution.suggestions || [])
            return 'suggestions'
          }

          if (resolution.status === 'exact' && resolution.matched_name) {
            target = resolution.matched_name
            resolvedExact = true
            tickerHint =
              resolution.suggestions?.find((item) => item.name === target)?.ticker ??
              resolution.suggestions?.[0]?.ticker ??
              null
            setQueryState(target)
          } else {
            setError(resolution.message || 'No valid companies found with this name.')
            return 'error'
          }
        }

        return await executeAnalyze(target, forceRefresh, requestId, {
          confirmed,
          resolved: resolvedExact,
          ticker: tickerHint,
          signal,
        })
      } catch (err) {
        if (requestId !== requestIdRef.current) return 'aborted'
        if (err instanceof ApiError && err.cancelled) return 'aborted'
        if (handleAuthError(err, trimmed)) {
          setError(null)
          return 'auth'
        }
        setError(err instanceof Error ? err.message : 'Analysis failed')
        setRunMetrics(null)
        setSuggestions([])
        setSuggestionMessage(null)
        return 'error'
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false)
          if (abortRef.current?.signal === signal) {
            abortRef.current = null
          }
        }
      }
    },
    [
      user,
      openAuth,
      continuePrivately,
      handleAuthError,
      executeAnalyze,
      clearAutocomplete,
      beginRequest,
      autocomplete,
    ],
  )

  const updateQuery = useCallback(
    (value: string) => {
      // Always reflect keystrokes immediately. Booting a private session (or
      // validating a token after hard refresh) can take seconds on a cold API —
      // that must not gate the controlled input, or typing appears broken.
      autocompleteLiveRef.current = true
      setQueryState(value)
      setError(null)
      if (suggestions.length > 0) {
        setSuggestions([])
        setSuggestionMessage(null)
      }
      if (!user) {
        void continuePrivately().catch(() =>
          openAuth({
            mode: 'signin',
            message: 'Start a private session or sign in to search companies.',
          }),
        )
      }
    },
    [suggestions.length, user, openAuth, continuePrivately],
  )

  // Live autocomplete while typing — signed-in users only.
  // Skip after Get insights / return home until the user edits the field again.
  useEffect(() => {
    if (!user) {
      clearAutocomplete()
      return
    }
    const trimmed = query.trim()
    // Keep autocomplete available while a brief builds so the user can edit / pivot.
    if (!autocompleteLiveRef.current || trimmed.length < 2 || !/[A-Za-z]/.test(trimmed)) {
      setAutocomplete([])
      setAutocompleteOpen(false)
      setActiveSuggestionIndex(-1)
      setAutocompleteLoading(false)
      return
    }

    const seq = ++autocompleteSeqRef.current
    setAutocompleteLoading(true)
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const items = await suggestCompanies(trimmed)
          if (seq !== autocompleteSeqRef.current || !autocompleteLiveRef.current) return
          startTransition(() => {
            setAutocomplete(items)
            setAutocompleteOpen(items.length > 0)
            setActiveSuggestionIndex(items.length > 0 ? 0 : -1)
          })
        } catch {
          if (seq !== autocompleteSeqRef.current) return
          setAutocomplete([])
          setAutocompleteOpen(false)
          setActiveSuggestionIndex(-1)
        } finally {
          if (seq === autocompleteSeqRef.current) {
            setAutocompleteLoading(false)
          }
        }
      })()
    }, AUTOCOMPLETE_DEBOUNCE_MS)

    return () => {
      window.clearTimeout(timer)
    }
  }, [query, user, clearAutocomplete, startTransition])

  const pickSuggestion = useCallback(
    async (suggestion: CompanySuggestion): Promise<RunAnalysisResult> => {
      setQueryState(suggestion.name)
      clearAutocomplete()
      setSuggestions([])
      setSuggestionMessage(null)
      return runAnalysis(suggestion.name, false, {
        skipResolve: true,
        confirmed: true,
        ticker: suggestion.ticker,
      })
    },
    [runAnalysis, clearAutocomplete],
  )

  const onSearchKeyDown = useCallback(
    (event: KeyboardEvent<HTMLInputElement>) => {
      if (!autocompleteOpen || autocomplete.length === 0) return

      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveSuggestionIndex((index) => (index + 1) % autocomplete.length)
        return
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveSuggestionIndex((index) => (index <= 0 ? autocomplete.length - 1 : index - 1))
        return
      }
      if (event.key === 'Escape') {
        event.preventDefault()
        setAutocompleteOpen(false)
        setActiveSuggestionIndex(-1)
      }
    },
    [autocompleteOpen, autocomplete.length],
  )

  // After successful sign-in/register, continue the company the guest typed.
  useEffect(() => {
    if (!user || !pendingCompany) return
    const company = pendingCompany
    clearPendingCompany()
    setQueryState(company)
    void runAnalysis(company)
  }, [user, pendingCompany, clearPendingCompany, runAnalysis])

  // Reset workspace when the account changes / signs out.
  useEffect(() => {
    if (user) {
      void loadHistory()
      return
    }
    // Abrupt sign-out / end-session: kill in-flight work and wipe the board.
    cancelAnalysis()
    setAnalysis(null)
    setRecent([])
    setHistoryLoaded(false)
    setHistoryLoading(false)
    setRunMetrics(null)
    setError(null)
    setHistoryError(null)
    setSuggestions([])
    setSuggestionMessage(null)
    setQueryState('')
    clearAutocomplete()
  }, [user?.id]) // eslint-disable-line react-hooks/exhaustive-deps -- intentional on identity change

  const openRecent = useCallback(
    async (id: number): Promise<RunAnalysisResult> => {
      if (!user) {
        openAuth({
          mode: 'signin',
          message: 'Sign in to reopen briefs from your library.',
        })
        return 'auth'
      }
      const { requestId, signal } = beginRequest()
      setLoading(true)
      setLoadingMode('open')
      setRunMetrics(null)
      setError(null)
      setSuggestions([])
      setSuggestionMessage(null)
      clearAutocomplete()
      try {
        const result = await getAnalysis(id, { signal })
        if (requestId !== requestIdRef.current) return 'aborted'
        setAnalysis(result)
        setQueryState(result.company_name)
        setRunMetrics(null)
        return 'analyzed'
      } catch (err) {
        if (requestId !== requestIdRef.current) return 'aborted'
        if (err instanceof ApiError && err.cancelled) return 'aborted'
        if (handleAuthError(err)) return 'auth'
        setError(err instanceof Error ? err.message : 'Could not load analysis')
        return 'error'
      } finally {
        if (requestId === requestIdRef.current) {
          setLoading(false)
          if (abortRef.current?.signal === signal) {
            abortRef.current = null
          }
        }
      }
    },
    [user, openAuth, handleAuthError, clearAutocomplete, beginRequest],
  )

  const value = useMemo<CompanyInsightsContextValue>(
    () => ({
      query,
      setQuery: updateQuery,
      analysis,
      recent,
      error,
      suggestions,
      suggestionMessage,
      autocomplete,
      autocompleteOpen,
      autocompleteLoading,
      activeSuggestionIndex,
      setAutocompleteOpen,
      setActiveSuggestionIndex,
      historyError,
      historyLoading,
      historyLoaded,
      loading,
      loadingMode,
      runMetrics,
      runAnalysis,
      cancelAnalysis,
      endSession,
      pickSuggestion,
      onSearchKeyDown,
      openRecent,
      loadHistory,
      clearHistory,
      clearWorkspaceError,
      clearRunMetrics,
    }),
    [
      query,
      updateQuery,
      analysis,
      recent,
      error,
      suggestions,
      suggestionMessage,
      autocomplete,
      autocompleteOpen,
      autocompleteLoading,
      activeSuggestionIndex,
      historyError,
      historyLoading,
      historyLoaded,
      loading,
      loadingMode,
      runMetrics,
      runAnalysis,
      cancelAnalysis,
      endSession,
      pickSuggestion,
      onSearchKeyDown,
      openRecent,
      loadHistory,
      clearHistory,
      clearWorkspaceError,
      clearRunMetrics,
    ],
  )

  return (
    <CompanyInsightsContext.Provider value={value}>{children}</CompanyInsightsContext.Provider>
  )
}

export function useCompanyInsights() {
  const ctx = useContext(CompanyInsightsContext)
  if (!ctx) {
    throw new Error('useCompanyInsights must be used within CompanyInsightsProvider')
  }
  return ctx
}

import { type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnalysisProgress } from '../components/AnalysisProgress'
import { BriefLibrary } from '../components/BriefLibrary'
import { useAuth } from '../hooks/useAuth'
import { useCompanyInsights } from '../hooks/useCompanyInsights'

/**
 * Home (/) — search + autocomplete + analyze progress + collapsible library.
 * After 100%, user clicks through to /insights (no auto-redirect).
 */
export function HomePage() {
  const navigate = useNavigate()
  const { user, ready, openAuth } = useAuth()
  const {
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
    suggestions,
    suggestionMessage,
    autocomplete,
    autocompleteOpen,
    autocompleteLoading,
    activeSuggestionIndex,
    setAutocompleteOpen,
    setActiveSuggestionIndex,
    runAnalysis,
    cancelAnalysis,
    pickSuggestion,
    onSearchKeyDown,
    openRecent,
    loadHistory,
    clearHistory,
  } = useCompanyInsights()

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    // Unsigned users auto-start a private session inside runAnalysis.
    await runAnalysis(query)
  }

  async function onPickSuggestion(item: Parameters<typeof pickSuggestion>[0]) {
    await pickSuggestion(item)
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' && autocompleteOpen && activeSuggestionIndex >= 0) {
      const chosen = autocomplete[activeSuggestionIndex]
      if (chosen) {
        event.preventDefault()
        void onPickSuggestion(chosen)
        return
      }
    }
    onSearchKeyDown(event)
  }

  // Keep the last completed run summary on home (collapsible) after returning from /insights.
  const showProgress = Boolean(
    ((loading && loadingMode === 'analyze') || runMetrics) && !error,
  )
  const briefReady = Boolean(!loading && analysis && runMetrics && !error)
  // Expand while building; when remounting after a finished run, start collapsed.
  const progressDefaultExpanded = loading

  const searchStage = (
    <div className="home-search-stage">
      <form className="search-console" onSubmit={(event) => void onSubmit(event)}>
        <label className="search-label" htmlFor="company-query">
          Company
        </label>
        {!user && (
          <p className="search-guest-hint">
            Typing starts a private session automatically.{" "}
            <button
              type="button"
              className="search-guest-link"
              disabled={!ready}
              onClick={() =>
                openAuth({
                  mode: 'signin',
                  message: 'Sign in to keep briefs under your email.',
                })
              }
            >
              Sign in
            </button>{" "}
            to save under your email.
          </p>
        )}
        <div className={`search-row${loading ? ' search-row--busy' : ''}`}>
          <div className="search-input-wrap">
            <input
              id="company-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleSearchKeyDown}
              onBlur={() => {
                window.setTimeout(() => setAutocompleteOpen(false), 120)
              }}
              placeholder="Microsoft, Nestlé, Siemens…"
              aria-label="Company name"
              aria-autocomplete="list"
              aria-expanded={autocompleteOpen}
              aria-controls="company-autocomplete"
              autoComplete="off"
            />
            {autocompleteOpen && autocomplete.length > 0 && (
              <ul
                id="company-autocomplete"
                className="company-autocomplete"
                role="listbox"
                aria-label="Company autocomplete"
              >
                {autocomplete.map((item, index) => (
                  <li
                    key={`ac-${item.source}-${item.name}-${item.location || item.ticker || ''}`}
                  >
                    <button
                      type="button"
                      role="option"
                      aria-selected={index === activeSuggestionIndex}
                      className={`company-autocomplete-btn${
                        index === activeSuggestionIndex ? ' is-active' : ''
                      }`}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setActiveSuggestionIndex(index)}
                      onClick={() => void onPickSuggestion(item)}
                    >
                      <span className="company-autocomplete-main">
                        <strong>{item.name}</strong>
                        {item.description && <span>{item.description}</span>}
                      </span>
                      <span className="company-autocomplete-meta">
                        {Math.round(item.confidence * 100)}%
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {autocompleteLoading && query.trim().length >= 2 && !autocompleteOpen && (
              <p className="company-autocomplete-status">Finding companies…</p>
            )}
          </div>
          {loading && (
            <button
              type="button"
              className="btn btn-stop"
              onClick={cancelAnalysis}
              aria-label="Stop building brief"
            >
              Stop
            </button>
          )}
          <button className="btn" type="submit" disabled={!query.trim()}>
            {loading ? 'Restart' : 'Get insights'}
          </button>
        </div>
      </form>

      {showProgress && (
        <div className="status-line" role="status" aria-live="polite">
          <AnalysisProgress
            active={loading && loadingMode === 'analyze'}
            mode="analyze"
            metrics={runMetrics}
            defaultExpanded={progressDefaultExpanded}
          />
          {loading && loadingMode === 'analyze' && (
            <div className="home-brief-ready-actions">
              <button
                type="button"
                className="btn btn-stop"
                onClick={cancelAnalysis}
                aria-label="Stop building brief"
              >
                Stop search
              </button>
            </div>
          )}
          {briefReady && (
            <div className="home-brief-ready-actions">
              <button
                type="button"
                className="btn home-view-insights-btn"
                onClick={() => navigate('/insights')}
              >
                View insights →
              </button>
            </div>
          )}
        </div>
      )}

      {!loading && suggestions.length > 0 && (
        <div className="company-suggestions" role="listbox" aria-label="Company suggestions">
          <p className="company-suggestions-lead">
            {suggestionMessage || 'Did you mean one of these companies?'}
          </p>
          <ul className="company-suggestions-list">
            {suggestions.map((item) => (
              <li key={`${item.source}-${item.name}-${item.ticker || ''}`}>
                <button
                  type="button"
                  className="company-suggestion-btn"
                  onClick={() => void onPickSuggestion(item)}
                  disabled={loading}
                >
                  <span className="company-suggestion-main">
                    <strong>{item.name}</strong>
                    {item.description && <span>{item.description}</span>}
                  </span>
                  <span className="company-suggestion-meta">
                    {Math.round(item.confidence * 100)}% match
                    {item.ticker ? ` · ${item.ticker}` : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <div className="status-line error" role="status" aria-live="polite">
          {error}
        </div>
      )}
    </div>
  )

  return (
    <div className={`page page--home${user ? ' page--home-split' : ''}`}>
      <section className="hero">
        <h1>
          <span className="brand-lockup">Company Insights</span>
          <span className="hero-line">
            Walk in <em>prepared</em>.
          </span>
        </h1>
        <p className="hero-lead">
          Enter a company. We gather the news and turn it into a partner-ready brief — themes,
          risks, opportunities, and what to say in the room.
        </p>
      </section>

      <div className={`workspace${user ? ' workspace--split home-workspace' : ''}`}>
        {searchStage}
        {user && (
          <BriefLibrary
            recent={recent}
            analysis={analysis}
            historyError={historyError}
            historyLoading={historyLoading}
            historyLoaded={historyLoaded}
            loading={loading}
            onLoadHistory={loadHistory}
            onClearHistory={clearHistory}
            onOpenRecent={async (id) => {
              const result = await openRecent(id)
              if (result === 'analyzed') navigate('/insights')
            }}
            collapsible
            defaultExpanded
          />
        )}
      </div>
    </div>
  )
}

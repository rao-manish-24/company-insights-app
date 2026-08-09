import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BriefLibrary } from '../components/BriefLibrary'
import { InsightsPanel } from '../components/InsightsPanel'
import { useAuth } from '../hooks/useAuth'
import { useCompanyInsights } from '../hooks/useCompanyInsights'

/**
 * Insights (/insights) — brief + library only.
 * Pipeline progress / token usage stays on home until the run completes.
 */
export function InsightsPage() {
  const navigate = useNavigate()
  const { user, ready, openAuth } = useAuth()
  const {
    analysis,
    recent,
    error,
    historyError,
    historyLoading,
    historyLoaded,
    loading,
    runAnalysis,
    cancelAnalysis,
    openRecent,
    loadHistory,
    clearHistory,
  } = useCompanyInsights()

  useEffect(() => {
    if (!ready) return
    if (!user) {
      openAuth({
        mode: 'signin',
        message: 'Sign in to view insights.',
      })
      navigate('/', { replace: true })
      return
    }
    // Analysis is produced on home first; bounce home when there is nothing to show.
    if (!analysis && !loading && !error) {
      navigate('/', { replace: true })
    }
  }, [ready, user, analysis, loading, error, navigate, openAuth])

  return (
    <div className="page page--insights">
      <section className="hero hero--compact">
        <div className="hero-compact-copy">
          <p className="hero-compact-brand">Insights</p>
          <p className="hero-compact-sub">
            {analysis
              ? `Brief for ${analysis.company_name}. Refresh for a new pull, or reopen another from the library.`
              : loading
                ? 'Loading brief…'
                : 'Open a brief from your library, or start a new search.'}
          </p>
        </div>
        <div className="insights-toolbar">
          <Link className="btn btn-secondary" to="/">
            ← New search
          </Link>
          {loading && (
            <button type="button" className="btn btn-stop" onClick={cancelAnalysis}>
              Stop
            </button>
          )}
          {analysis && (
            <button
              type="button"
              className="btn"
              disabled={loading}
              onClick={() =>
                void runAnalysis(analysis.company_name, true, {
                  skipResolve: true,
                  confirmed: true,
                })
              }
            >
              {loading ? 'Refreshing…' : 'Refresh brief'}
            </button>
          )}
        </div>

        {(error || (analysis?.cached && !loading)) && (
          <div className={`status-line ${error ? 'error' : ''}`} role="status" aria-live="polite">
            {error}
            {!loading && !error && analysis?.cached && (
              <span className="status-cached">
                Showing a recent cached brief for this company. Refresh for a new pull.
              </span>
            )}
          </div>
        )}
      </section>

      <div className="workspace workspace--split">
        <main className="workspace-main">
          {analysis ? (
            <InsightsPanel
              analysis={analysis}
              onRefresh={() =>
                void runAnalysis(analysis.company_name, true, {
                  skipResolve: true,
                  confirmed: true,
                })
              }
              refreshing={loading}
            />
          ) : (
            <div className="insights-waiting">
              <p>{loading ? 'Loading brief…' : 'No brief selected.'}</p>
            </div>
          )}
        </main>

        <BriefLibrary
          recent={recent}
          analysis={analysis}
          historyError={historyError}
          historyLoading={historyLoading}
          historyLoaded={historyLoaded}
          loading={loading}
          onLoadHistory={loadHistory}
          onClearHistory={clearHistory}
          onOpenRecent={openRecent}
        />
      </div>
    </div>
  )
}

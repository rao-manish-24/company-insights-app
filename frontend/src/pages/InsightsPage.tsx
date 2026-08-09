import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { InsightsPanel } from '../components/InsightsPanel'
import { useAuth } from '../hooks/useAuth'
import { useCompanyInsights } from '../hooks/useCompanyInsights'

function formatLibraryDate(iso: string) {
  const date = new Date(iso)
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()

  if (sameDay) {
    return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  }

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() === now.getFullYear() ? undefined : 'numeric',
  })
}

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

  async function onOpenRecent(id: number) {
    await openRecent(id)
  }

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

        <aside className="workspace-aside">
          <div className="aside-head">
            <p className="section-label">Library</p>
            <h2>Recent briefs</h2>
            <p className="aside-lead">
              {historyLoaded
                ? recent.length > 0
                  ? `${recent.length} brief${recent.length === 1 ? '' : 's'} ready to reopen.`
                  : 'No saved briefs yet.'
                : 'Load your previous searches.'}
            </p>
          </div>
          <div className="library-actions">
            <button
              type="button"
              className="btn btn-secondary library-btn"
              onClick={() => void loadHistory()}
              disabled={loading || historyLoading}
            >
              {historyLoading ? 'Loading…' : 'Last 15'}
            </button>
            <button
              type="button"
              className="btn btn-ghost library-btn"
              onClick={() => void clearHistory()}
              disabled={loading || historyLoading}
            >
              Clear history
            </button>
          </div>
          {historyError && <p className="email-status error">{historyError}</p>}
          {recent.length === 0 ? (
            <p className="empty-hint">Library is empty.</p>
          ) : (
            <div className="history-list">
              {recent.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  className={`history-btn ${analysis?.id === item.id ? 'active' : ''}`}
                  onClick={() => void onOpenRecent(item.id)}
                  disabled={loading || historyLoading}
                >
                  <span className="history-top">
                    <span className="history-name-row">
                      <span className="history-index" aria-hidden="true">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <strong>{item.company_name}</strong>
                    </span>
                    <time dateTime={item.created_at}>{formatLibraryDate(item.created_at)}</time>
                  </span>
                  <span className="history-excerpt">
                    {item.executive_summary.slice(0, 110)}
                    {item.executive_summary.length > 110 ? '…' : ''}
                  </span>
                </button>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

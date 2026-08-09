import { type FormEvent } from 'react'
import { AnalysisProgress } from './components/AnalysisProgress'
import { AuthModal } from './components/AuthModal'
import { InsightsPanel } from './components/InsightsPanel'
import { useAuth } from './hooks/useAuth'
import { useCompanyInsights } from './hooks/useCompanyInsights'

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

function App() {
  const { user, ready, openAuth, signOut } = useAuth()
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
    runAnalysis,
    openRecent,
    loadHistory,
    clearHistory,
  } = useCompanyInsights()

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    void runAnalysis(query)
  }

  const hasBrief = Boolean(analysis)

  return (
    <div className={`app ${hasBrief ? 'app--brief' : 'app--home'}`}>
      <div className="atmosphere" aria-hidden="true">
        <div className="atmosphere-grid" />
        <div className="atmosphere-glow atmosphere-glow--a" />
        <div className="atmosphere-glow atmosphere-glow--b" />
        <div className="atmosphere-ring" />
      </div>

      <div className="app-shell">
        <header className="topbar">
          <a className="brand-mark" href="/" aria-label="Company Insights home">
            <span className="brand-mark-icon" aria-hidden="true">
              <span className="brand-mark-core" />
            </span>
            <span className="brand-word">Company Insights</span>
          </a>
          <div className="topbar-actions">
            <span className="topbar-note">News → insight → next move</span>
            {ready && user ? (
              <div className="topbar-user">
                <span className="topbar-user-email" title={user.email}>
                  {user.display_name || user.email}
                </span>
                <button type="button" className="btn btn-ghost topbar-auth-btn" onClick={signOut}>
                  Sign out
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn-secondary topbar-auth-btn"
                onClick={() => openAuth({ mode: 'signin' })}
                disabled={!ready}
              >
                Sign in
              </button>
            )}
          </div>
        </header>

        <section className={`hero ${hasBrief ? 'hero--compact' : ''}`}>
          {!hasBrief && (
            <>
              <h1>
                <span className="brand-lockup">Company Insights</span>
                <span className="hero-line">
                  Walk in <em>prepared</em>.
                </span>
              </h1>
              <p className="hero-lead">
                Enter a company. We gather the news and turn it into a partner-ready brief —
                themes, risks, opportunities, and what to say in the room.
              </p>
            </>
          )}

          {hasBrief && (
            <div className="hero-compact-copy">
              <p className="hero-compact-brand">Company Insights</p>
              <p className="hero-compact-sub">
                Generate another brief, refresh the open one, or reopen from the library.
              </p>
            </div>
          )}

          <form className="search-console" onSubmit={onSubmit}>
            <label className="search-label" htmlFor="company-query">
              Company
            </label>
            <div className="search-row">
              <input
                id="company-query"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Microsoft, Nestlé, Siemens…"
                aria-label="Company name"
                disabled={loading}
                autoComplete="organization"
              />
              <button className="btn" type="submit" disabled={loading || !query.trim()}>
                {loading ? 'Analyzing…' : hasBrief ? 'Generate' : 'Generate insights'}
              </button>
            </div>
          </form>

          <div className={`status-line ${error ? 'error' : ''}`} role="status" aria-live="polite">
            {(loading || runMetrics) && !error && (
              <AnalysisProgress active={loading} mode={loadingMode} metrics={runMetrics} />
            )}
            {!loading && error}
            {!loading && !error && analysis?.cached && !runMetrics && (
              <span className="status-cached">
                Showing a recent cached brief for this company. Refresh for a new pull.
              </span>
            )}
          </div>
        </section>

        {!hasBrief && (
          <section className="process-band" aria-label="How it works">
            <div className="process-item">
              <span className="process-num">01</span>
              <div>
                <h2>News intake</h2>
                <p>
                  Recent public coverage pulled for the company you name, with sources kept for
                  evidence.
                </p>
              </div>
            </div>
            <div className="process-item">
              <span className="process-num">02</span>
              <div>
                <h2>Insight agent</h2>
                <p>
                  Themes, upside, risks, recommendations, and talk tracks grounded in that news —
                  plus a company snapshot.
                </p>
              </div>
            </div>
            <div className="process-item">
              <span className="process-num">03</span>
              <div>
                <h2>Reusable brief</h2>
                <p>
                  Saved in your private library after you sign in — reopen before the client
                  conversation, email, or refresh.
                </p>
              </div>
            </div>
          </section>
        )}

        <div className={`workspace ${hasBrief ? 'workspace--split' : ''}`}>
          {hasBrief && analysis && (
            <main className="workspace-main">
              <InsightsPanel
                analysis={analysis}
                onRefresh={() => void runAnalysis(analysis.company_name, true)}
                refreshing={loading}
              />
            </main>
          )}

          <aside className={`workspace-aside ${hasBrief ? '' : 'workspace-aside--home'}`}>
            <div className="aside-head">
              <p className="section-label">Library</p>
              <h2>Recent briefs</h2>
              <p className="aside-lead">
                {!user
                  ? 'Sign in to load your private library.'
                  : historyLoaded
                    ? recent.length > 0
                      ? `${recent.length} brief${recent.length === 1 ? '' : 's'} ready to reopen.`
                      : 'No saved briefs yet.'
                    : 'Load your previous searches, or generate a new brief.'}
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
                disabled={loading || historyLoading || !user}
              >
                Clear history
              </button>
            </div>
            {historyError && <p className="email-status error">{historyError}</p>}
            {!user ? (
              <p className="empty-hint">
                Sign in to generate insights and keep briefs private to your account.
              </p>
            ) : !historyLoaded && recent.length === 0 ? (
              <p className="empty-hint">Use Last 15 to load previous search results from the library.</p>
            ) : recent.length === 0 ? (
              <p className="empty-hint">Library is empty. Generate a brief to start a history.</p>
            ) : (
              <div className="history-list">
                {recent.map((item, index) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`history-btn ${analysis?.id === item.id ? 'active' : ''}`}
                    onClick={() => void openRecent(item.id)}
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

      <AuthModal />
    </div>
  )
}

export default App

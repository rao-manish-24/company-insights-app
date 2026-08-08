import { type FormEvent } from 'react'
import { InsightsPanel } from './components/InsightsPanel'
import { useCompanyInsights } from './hooks/useCompanyInsights'

function App() {
  const {
    query,
    setQuery,
    analysis,
    recent,
    error,
    historyError,
    loading,
    runAnalysis,
    openRecent,
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
          <span className="topbar-note">News → insight → next move</span>
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
              <p className="hero-compact-sub">Generate another brief or reopen one from the library.</p>
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
            {loading && (
              <span className="loading">
                <span className="spinner" aria-hidden="true" />
                Gathering coverage and drafting the brief…
              </span>
            )}
            {!loading && error}
            {!loading && !error && analysis?.cached && 'Showing a recent cached brief for this company.'}
          </div>
        </section>

        {!hasBrief && (
          <section className="process-band" aria-label="How it works">
            <div className="process-item">
              <span className="process-num">01</span>
              <div>
                <h2>News intake</h2>
                <p>Recent coverage pulled for the company you name.</p>
              </div>
            </div>
            <div className="process-item">
              <span className="process-num">02</span>
              <div>
                <h2>Insight agent</h2>
                <p>Themes, upside, risks, and talk tracks grounded in that news.</p>
              </div>
            </div>
            <div className="process-item">
              <span className="process-num">03</span>
              <div>
                <h2>Reusable brief</h2>
                <p>Saved for quick revisit before the client conversation.</p>
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
            </div>
            {historyError && <p className="email-status error">{historyError}</p>}
            {recent.length === 0 ? (
              <p className="empty-hint">Your generated briefs will land here.</p>
            ) : (
              <div className="history-list">
                {recent.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`history-btn ${analysis?.id === item.id ? 'active' : ''}`}
                    onClick={() => void openRecent(item.id)}
                    disabled={loading}
                  >
                    <span className="history-top">
                      <strong>{item.company_name}</strong>
                      <time dateTime={item.created_at}>
                        {new Date(item.created_at).toLocaleDateString(undefined, {
                          month: 'short',
                          day: 'numeric',
                        })}
                      </time>
                    </span>
                    <span className="history-excerpt">
                      {item.executive_summary.slice(0, 96)}
                      {item.executive_summary.length > 96 ? '…' : ''}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}

export default App

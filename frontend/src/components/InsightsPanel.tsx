import { useState } from 'react'
import type { CompanyAnalysis } from '../types'
import { EmailBriefForm } from './EmailBriefForm'

interface Props {
  analysis: CompanyAnalysis
  onRefresh: () => void
  refreshing: boolean
}

function Badge({ level }: { level?: string }) {
  if (!level) return null
  const normalized = level.toLowerCase()
  const className = ['high', 'medium', 'low'].includes(normalized) ? normalized : 'medium'
  return <span className={`badge ${className}`}>{normalized}</span>
}

function EmptyHint({ label }: { label: string }) {
  return <p className="empty-hint">No {label} available for this brief.</p>
}

export function InsightsPanel({ analysis, onRefresh, refreshing }: Props) {
  const [showEmail, setShowEmail] = useState(false)

  return (
    <article className="brief">
      <header className="brief-header">
        <div className="brief-header-copy">
          <p className="section-label">Executive brief</p>
          <h1 className="brief-title">{analysis.company_name}</h1>
          <div className="brief-meta">
            <time dateTime={analysis.created_at}>
              {new Date(analysis.created_at).toLocaleString()}
            </time>
            <span aria-hidden="true">·</span>
            <span>{analysis.llm_model}</span>
            {analysis.cached && (
              <>
                <span aria-hidden="true">·</span>
                <span>Cached</span>
              </>
            )}
          </div>
        </div>
        <div className="brief-actions">
          <button className="btn btn-ghost" type="button" onClick={onRefresh} disabled={refreshing}>
            Refresh
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => setShowEmail((value) => !value)}
          >
            {showEmail ? 'Hide email' : 'Email brief'}
          </button>
        </div>
      </header>

      <section className="brief-section brief-section--summary">
        <p className="summary">{analysis.executive_summary}</p>
      </section>

      {showEmail && (
        <section className="brief-section brief-section--email">
          <EmailBriefForm analysisId={analysis.id} />
        </section>
      )}

      <section className="brief-section">
        <div className="brief-section-head">
          <p className="section-label">Signal scan</p>
          <h2>Key themes</h2>
        </div>
        {analysis.key_themes.length === 0 ? (
          <EmptyHint label="themes" />
        ) : (
          <div className="theme-grid">
            {analysis.key_themes.map((theme, index) => (
              <article className="theme-card" key={`${theme.theme}-${index}`}>
                <span className="index-mark" aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <h3>{theme.theme}</h3>
                <p>{theme.insight}</p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="brief-section">
        <div className="split-board">
          <div>
            <div className="brief-section-head">
              <p className="section-label">Upside</p>
              <h2>Opportunities</h2>
            </div>
            {analysis.opportunities.length === 0 ? (
              <EmptyHint label="opportunities" />
            ) : (
              <ul className="signal-list">
                {analysis.opportunities.map((item, index) => (
                  <li key={`${item.title}-${index}`}>
                    <div className="signal-title-row">
                      <h3>{item.title}</h3>
                      <Badge level={item.priority} />
                    </div>
                    <p>{item.detail}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <div className="brief-section-head">
              <p className="section-label">Watchouts</p>
              <h2>Risks</h2>
            </div>
            {analysis.risks.length === 0 ? (
              <EmptyHint label="risks" />
            ) : (
              <ul className="signal-list signal-list--risk">
                {analysis.risks.map((item, index) => (
                  <li key={`${item.title}-${index}`}>
                    <div className="signal-title-row">
                      <h3>{item.title}</h3>
                      <Badge level={item.severity} />
                    </div>
                    <p>{item.detail}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      <section className="brief-section">
        <div className="brief-section-head">
          <p className="section-label">Next moves</p>
          <h2>Recommendations</h2>
        </div>
        {analysis.recommendations.length === 0 ? (
          <EmptyHint label="recommendations" />
        ) : (
          <ol className="reco-list">
            {analysis.recommendations.map((item, index) => (
              <li key={`${item.action}-${index}`}>
                <span className="index-mark" aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div>
                  <h3>{item.action}</h3>
                  <p>{item.rationale}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="brief-section">
        <div className="brief-section-head">
          <p className="section-label">Meeting prep</p>
          <h2>Conversation starters</h2>
        </div>
        {analysis.conversation_starters.length === 0 ? (
          <EmptyHint label="conversation starters" />
        ) : (
          <ul className="starters">
            {analysis.conversation_starters.map((starter, index) => (
              <li key={`${starter}-${index}`}>
                <span className="index-mark" aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <p>{starter}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="brief-section brief-section--sources">
        <div className="brief-section-head">
          <p className="section-label">Evidence</p>
          <h2>Source news</h2>
        </div>
        {analysis.articles.length === 0 ? (
          <EmptyHint label="source articles" />
        ) : (
          <div className="articles">
            {analysis.articles.map((article, index) => {
              const meta = [
                article.source,
                article.published_at
                  ? new Date(article.published_at).toLocaleDateString()
                  : null,
              ]
                .filter(Boolean)
                .join(' · ')

              const body = (
                <>
                  <span className="article-index" aria-hidden="true">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className="article-copy">
                    <span className="article-title">{article.title}</span>
                    {meta && <span className="article-meta">{meta}</span>}
                  </span>
                  {article.url && (
                    <span className="article-arrow" aria-hidden="true">
                      ↗
                    </span>
                  )}
                </>
              )

              if (article.url) {
                return (
                  <a
                    key={`${article.title}-${index}`}
                    className="article-link"
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {body}
                  </a>
                )
              }

              return (
                <div key={`${article.title}-${index}`} className="article-link article-link--static">
                  {body}
                </div>
              )
            })}
          </div>
        )}
      </section>
    </article>
  )
}

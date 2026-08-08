import { useState } from 'react'
import type { CompanyAnalysis, CompanyProfile } from '../types'
import { EmailBriefForm } from './EmailBriefForm'

function profileHasContent(profile?: CompanyProfile | null) {
  if (!profile) return false
  const facts = [
    profile.founded,
    profile.headquarters,
    profile.employees,
    profile.parent_company,
    profile.revenue,
    profile.operating_income,
    profile.total_assets,
  ]
  const people = (profile.key_people || []).some((person) => Boolean(person.name))
  return facts.some(Boolean) || people
}

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
  const profile = analysis.company_profile
  const factRows = (
    [
      ['Founded', profile?.founded],
      ['Headquarters', profile?.headquarters],
      ['Employees', profile?.employees],
      ['Parent company', profile?.parent_company],
      ['Revenue', profile?.revenue],
      ['Operating income', profile?.operating_income],
      ['Total assets', profile?.total_assets],
    ] as const
  ).filter(([, value]) => Boolean(value))

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
            <span className="meta-sep" aria-hidden="true" />
            <span>{analysis.llm_model}</span>
            {analysis.cached && (
              <>
                <span className="meta-sep" aria-hidden="true" />
                <span className="meta-pill">Cached</span>
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
        <p className="section-label">At a glance</p>
        <p className="summary">{analysis.executive_summary}</p>
      </section>

      {showEmail && (
        <section className="brief-section brief-section--email">
          <EmailBriefForm analysisId={analysis.id} />
        </section>
      )}

      {profileHasContent(profile) && (
        <section className="brief-section brief-section--profile">
          <div className="brief-section-head">
            <p className="section-label">Company snapshot</p>
            <h2>Profile & leadership</h2>
          </div>

          {factRows.length > 0 && (
            <dl className="fact-table">
              {factRows.map(([label, value]) => (
                <div className="fact-row" key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          )}

          <div className="leadership-block">
            <p className="subsection-label">Key people</p>
            <ul className="leadership-grid">
              {(profile?.key_people || []).map((person) => (
                <li key={person.role}>
                  <span>{person.role}</span>
                  <strong className={person.name ? '' : 'is-empty'}>
                    {person.name || 'Not available'}
                  </strong>
                </li>
              ))}
            </ul>
          </div>

          {profile?.source_url && (
            <p className="profile-source">
              Source:{' '}
              <a href={profile.source_url} target="_blank" rel="noopener noreferrer">
                {profile.source || 'Wikidata'}
              </a>
            </p>
          )}
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
                <div>
                  <h3>{theme.theme}</h3>
                  <p>{theme.insight}</p>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="brief-section">
        <div className="split-board">
          <div className="split-pane">
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

          <div className="split-pane split-pane--risk">
            <div className="brief-section-head">
              <p className="section-label">Watchouts</p>
              <h2>Risks</h2>
            </div>
            {analysis.risks.length === 0 ? (
              <EmptyHint label="risks" />
            ) : (
              <ul className="signal-list">
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

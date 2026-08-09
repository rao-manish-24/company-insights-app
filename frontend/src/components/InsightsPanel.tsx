import { useState } from 'react'
import { expandInsight } from '../api'
import type {
  CompanyAnalysis,
  CompanyProfile,
  ExpandInsightKind,
  ExpandInsightResult,
  MarketSnapshot,
  NewsArticle,
  Opportunity,
  Recommendation,
  Risk,
} from '../types'
import { matchSources } from '../utils/matchSources'
import { EmailBriefForm } from './EmailBriefForm'
import { InsightDrillModal } from './InsightDrillModal'

function marketHasContent(market?: MarketSnapshot | null) {
  if (!market) return false
  return Boolean(
    market.ticker ||
      market.price ||
      market.market_cap ||
      market.sector ||
      market.industry,
  )
}

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
  return facts.some(Boolean) || people || marketHasContent(profile.market)
}

function formatWhen(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
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

const BRIEF_NAV = [
  { id: 'brief-summary', label: 'Summary' },
  { id: 'brief-profile', label: 'Profile' },
  { id: 'brief-themes', label: 'Themes' },
  { id: 'brief-signals', label: 'Signals' },
  { id: 'brief-moves', label: 'Moves' },
  { id: 'brief-talk', label: 'Talk tracks' },
  { id: 'brief-sources', label: 'Sources' },
] as const

type OpenInsight = {
  kind: ExpandInsightKind
  index: number
}

export function InsightsPanel({ analysis, onRefresh, refreshing }: Props) {
  const [showEmail, setShowEmail] = useState(false)
  const [openInsight, setOpenInsight] = useState<OpenInsight | null>(null)
  const [expandLoading, setExpandLoading] = useState(false)
  const [deepLoading, setDeepLoading] = useState(false)
  const [expandError, setExpandError] = useState<string | null>(null)
  const [expandedByKey, setExpandedByKey] = useState<Record<string, ExpandInsightResult>>({})
  const [deepByKey, setDeepByKey] = useState<Record<string, ExpandInsightResult>>({})
  const profile = analysis.company_profile
  const market = profile?.market

  function insightKey(kind: ExpandInsightKind, index: number) {
    return `${analysis.id}:${kind}:${index}`
  }

  function openDrill(kind: ExpandInsightKind, index: number) {
    setExpandError(null)
    setOpenInsight({ kind, index })
  }

  function closeDrill() {
    setOpenInsight(null)
    setExpandError(null)
  }

  async function askMore(kind: ExpandInsightKind, index: number) {
    const key = insightKey(kind, index)
    if (expandedByKey[key]) return
    setExpandLoading(true)
    setExpandError(null)
    try {
      const result = await expandInsight(analysis.id, kind, index, { depth: 'standard' })
      setExpandedByKey((current) => ({ ...current, [key]: result }))
    } catch (err) {
      setExpandError(err instanceof Error ? err.message : 'Could not expand this insight')
    } finally {
      setExpandLoading(false)
    }
  }

  async function askDeep(kind: ExpandInsightKind, index: number) {
    const key = insightKey(kind, index)
    if (deepByKey[key]) return
    const prior = expandedByKey[key]
    setDeepLoading(true)
    setExpandError(null)
    try {
      const result = await expandInsight(analysis.id, kind, index, {
        depth: 'deep',
        priorAnalysis: [
          prior?.deeper_analysis,
          prior?.why_it_matters,
          ...(prior?.suggested_moves || []),
        ]
          .filter(Boolean)
          .join('\n\n'),
      })
      setDeepByKey((current) => ({ ...current, [key]: result }))
    } catch (err) {
      setExpandError(err instanceof Error ? err.message : 'Could not run deep-dive agent')
    } finally {
      setDeepLoading(false)
    }
  }

  function sourcesFor(item: Opportunity | Risk | Recommendation): NewsArticle[] {
    return matchSources(item, analysis.articles)
  }

  const activeItem = (() => {
    if (!openInsight) return null
    if (openInsight.kind === 'opportunity') {
      const item = analysis.opportunities[openInsight.index]
      return item
        ? {
            kind: openInsight.kind,
            index: openInsight.index,
            heading: item.title,
            summary: item.detail,
            item,
          }
        : null
    }
    if (openInsight.kind === 'risk') {
      const item = analysis.risks[openInsight.index]
      return item
        ? {
            kind: openInsight.kind,
            index: openInsight.index,
            heading: item.title,
            summary: item.detail,
            item,
          }
        : null
    }
    const item = analysis.recommendations[openInsight.index]
    return item
      ? {
          kind: openInsight.kind,
          index: openInsight.index,
          heading: item.action,
          summary: item.rationale,
          item,
        }
      : null
  })()

  const activeKey = activeItem ? insightKey(activeItem.kind, activeItem.index) : null
  const activeExpanded = activeKey ? expandedByKey[activeKey] || null : null
  const activeDeep = activeKey ? deepByKey[activeKey] || null : null
  const activeSources = activeItem
    ? (activeExpanded?.sources as NewsArticle[] | undefined) ||
      (activeDeep?.sources as NewsArticle[] | undefined) ||
      sourcesFor(activeItem.item)
    : []
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

  const marketRows = (
    [
      ['Ticker', market?.ticker],
      ['Price', market?.price],
      ['Change', market?.change_percent],
      ['Previous close', market?.previous_close],
      ['Market cap', market?.market_cap],
      ['P/E (TTM)', market?.pe_ratio],
      ['Forward P/E', market?.forward_pe],
      ['EPS (TTM)', market?.eps],
      ['Dividend yield', market?.dividend_yield],
      ['Beta', market?.beta],
      ['52-week high', market?.fifty_two_week_high],
      ['52-week low', market?.fifty_two_week_low],
      ['Volume', market?.volume],
      ['Avg volume', market?.avg_volume],
      ['Sector', market?.sector],
      ['Industry', market?.industry],
      ['Exchange', market?.exchange],
    ] as const
  ).filter(([, value]) => Boolean(value))

  const showProfile = profileHasContent(profile)
  const showMarket = marketHasContent(market)
  const navItems = BRIEF_NAV.filter((item) => item.id !== 'brief-profile' || showProfile)

  const dossier = [
    { label: 'Themes', value: analysis.key_themes.length },
    { label: 'Opportunities', value: analysis.opportunities.length },
    { label: 'Risks', value: analysis.risks.length },
    { label: 'Actions', value: analysis.recommendations.length },
    { label: 'Sources', value: analysis.articles.length },
  ]

  return (
    <article className="brief">
      <header className="brief-header">
        <div className={`brief-header-top ${showMarket ? 'brief-header-top--split' : ''}`}>
          <div className="brief-header-copy">
            <p className="section-label">Executive brief</p>
            <h1 className="brief-title">{analysis.company_name}</h1>
            {profile?.matched_label && profile.matched_label !== analysis.company_name && (
              <p className="brief-aka">Matched as {profile.matched_label}</p>
            )}
            <div className="brief-meta">
              <time dateTime={analysis.created_at}>{formatWhen(analysis.created_at)}</time>
              <span className="meta-sep" aria-hidden="true" />
              <span className="meta-model" title="Model used for this brief">
                {analysis.llm_model}
              </span>
              {analysis.cached && (
                <>
                  <span className="meta-sep" aria-hidden="true" />
                  <span className="meta-pill">Cached</span>
                </>
              )}
            </div>
            <div className="brief-actions">
              <button className="btn btn-ghost" type="button" onClick={onRefresh} disabled={refreshing}>
                {refreshing ? 'Refreshing…' : 'Refresh'}
              </button>
              <button
                className="btn btn-secondary"
                type="button"
                onClick={() => setShowEmail((value) => !value)}
              >
                {showEmail ? 'Hide email' : 'Email brief'}
              </button>
            </div>
          </div>

          {showMarket && market && (
            <aside className="header-market" aria-label="Market snapshot">
              <div className="header-market-head">
                <p className="section-label">Market snapshot</p>
                {market.ticker && <span className="market-ticker">{market.ticker}</span>}
              </div>
              {market.price && (
                <p className="header-market-price">
                  <span className="market-price">{market.price}</span>
                  {market.change_percent && (
                    <span
                      className={`market-change ${
                        market.change_percent.startsWith('-') ? 'is-down' : 'is-up'
                      }`}
                    >
                      {market.change_percent}
                    </span>
                  )}
                </p>
              )}
              <dl className="header-market-stats">
                {market.market_cap && (
                  <div>
                    <dt>Market cap</dt>
                    <dd>{market.market_cap}</dd>
                  </div>
                )}
                {market.pe_ratio && (
                  <div>
                    <dt>P/E</dt>
                    <dd>{market.pe_ratio}</dd>
                  </div>
                )}
                {market.sector && (
                  <div>
                    <dt>Sector</dt>
                    <dd>{market.sector}</dd>
                  </div>
                )}
                {market.industry && (
                  <div>
                    <dt>Industry</dt>
                    <dd>{market.industry}</dd>
                  </div>
                )}
              </dl>
              {market.source_url && (
                <a
                  className="header-market-link"
                  href={market.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Yahoo Finance ↗
                </a>
              )}
            </aside>
          )}
        </div>
      </header>

      <div className="brief-dossier" aria-label="Brief contents overview">
        {dossier.map((item) => (
          <div className="dossier-cell" key={item.label}>
            <span className="dossier-value">{item.value}</span>
            <span className="dossier-label">{item.label}</span>
          </div>
        ))}
      </div>

      <nav className="brief-nav" aria-label="Jump to brief section">
        {navItems.map((item) => (
          <a key={item.id} className="brief-nav-link" href={`#${item.id}`}>
            {item.label}
          </a>
        ))}
      </nav>

      <section className="brief-section brief-section--summary" id="brief-summary">
        <div className="brief-section-head">
          <p className="section-label">At a glance</p>
          <h2>Executive summary</h2>
          <p className="section-lead">
            The partner-ready read of what matters in the current news cycle.
          </p>
        </div>
        <p className="summary">{analysis.executive_summary}</p>
      </section>

      {showEmail && (
        <section className="brief-section brief-section--email">
          <EmailBriefForm analysisId={analysis.id} />
        </section>
      )}

      {showProfile && (
        <section className="brief-section brief-section--profile" id="brief-profile">
          <div className="brief-section-head">
            <p className="section-label">Company snapshot</p>
            <h2>Profile & leadership</h2>
            <p className="section-lead">
              Context to orient the room before the conversation turns to news and strategy.
            </p>
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

          {showMarket && marketRows.length > 0 && (
            <div className="market-block">
              <p className="subsection-label">Full market detail</p>
              <dl className="fact-table fact-table--market">
                {marketRows.map(([label, value]) => (
                  <div className="fact-row" key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
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

          {(profile?.source_url || profile?.wikipedia_url) && (
            <p className="profile-source">
              Company source:{' '}
              {profile.source_url ? (
                <a href={profile.source_url} target="_blank" rel="noopener noreferrer">
                  {profile.source?.includes('Wikipedia') && profile.source_url.includes('wikidata')
                    ? 'Wikidata'
                    : profile.source || 'Wikidata'}
                </a>
              ) : null}
              {profile.source_url && profile.wikipedia_url ? ' + ' : null}
              {profile.wikipedia_url ? (
                <a href={profile.wikipedia_url} target="_blank" rel="noopener noreferrer">
                  Wikipedia
                </a>
              ) : null}
            </p>
          )}
        </section>
      )}

      <section className="brief-section" id="brief-themes">
        <div className="brief-section-head">
          <p className="section-label">Signal scan</p>
          <h2>Key themes</h2>
          <p className="section-lead">
            Recurring storylines in the coverage — each with the insight a partner can act on.
          </p>
        </div>
        {analysis.key_themes.length === 0 ? (
          <EmptyHint label="themes" />
        ) : (
          <div className="theme-grid">
            {analysis.key_themes.map((theme, index) => (
              <article className="theme-item" key={`${theme.theme}-${index}`}>
                <span className="index-mark" aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div>
                  <h3>{theme.theme}</h3>
                  <p>{theme.insight}</p>
                  {theme.evidence && theme.evidence.length > 0 && (
                    <ul className="evidence-list">
                      {theme.evidence.map((line, evidenceIndex) => (
                        <li key={`${theme.theme}-ev-${evidenceIndex}`}>{line}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="brief-section" id="brief-signals">
        <div className="brief-section-head brief-section-head--inline">
          <div>
            <p className="section-label">Balanced view</p>
            <h2>Opportunities & risks</h2>
          </div>
        </div>
        <div className="split-board">
          <div className="split-pane split-pane--upside">
            <div className="brief-section-head">
              <p className="section-label">Upside</p>
              <h2>Opportunities</h2>
            </div>
            {analysis.opportunities.length === 0 ? (
              <EmptyHint label="opportunities" />
            ) : (
              <ul className="signal-list">
                {analysis.opportunities.map((item, index) => (
                  <li key={`${item.title}-${index}`} className="signal-item">
                    <button
                      type="button"
                      className="signal-item-trigger"
                      onClick={() => openDrill('opportunity', index)}
                    >
                      <div className="signal-title-row">
                        <h3>{item.title}</h3>
                        <Badge level={item.priority} />
                      </div>
                      <p>{item.detail}</p>
                      <span className="signal-hint">Open dig-deeper popup</span>
                    </button>
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
                  <li key={`${item.title}-${index}`} className="signal-item">
                    <button
                      type="button"
                      className="signal-item-trigger"
                      onClick={() => openDrill('risk', index)}
                    >
                      <div className="signal-title-row">
                        <h3>{item.title}</h3>
                        <Badge level={item.severity} />
                      </div>
                      <p>{item.detail}</p>
                      <span className="signal-hint">Open dig-deeper popup</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      <section className="brief-section" id="brief-moves">
        <div className="brief-section-head">
          <p className="section-label">Next moves</p>
          <h2>Recommendations</h2>
          <p className="section-lead">
            Concrete actions and the rationale to defend them in the room. Click any item to open
            the dig-deeper popup.
          </p>
        </div>
        {analysis.recommendations.length === 0 ? (
          <EmptyHint label="recommendations" />
        ) : (
          <ol className="reco-list">
            {analysis.recommendations.map((item, index) => (
              <li key={`${item.action}-${index}`} className="reco-item">
                <button
                  type="button"
                  className="reco-item-trigger"
                  onClick={() => openDrill('recommendation', index)}
                >
                  <span className="index-mark" aria-hidden="true">
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <div>
                    <h3>{item.action}</h3>
                    <p>{item.rationale}</p>
                    <span className="signal-hint">Open dig-deeper popup</span>
                  </div>
                </button>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="brief-section" id="brief-talk">
        <div className="brief-section-head">
          <p className="section-label">Meeting prep</p>
          <h2>Conversation starters</h2>
          <p className="section-lead">
            Openers that sound informed — not rehearsed — when you sit down with the client.
          </p>
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

      <section className="brief-section brief-section--sources" id="brief-sources">
        <div className="brief-section-head">
          <p className="section-label">Evidence</p>
          <h2>Source news</h2>
          <p className="section-lead">
            The coverage grounding this brief. Open a link to verify or go deeper.
          </p>
        </div>
        {analysis.articles.length === 0 ? (
          <EmptyHint label="source articles" />
        ) : (
          <div className="articles">
            {analysis.articles.map((article, index) => {
              const meta = [
                article.source,
                article.published_at
                  ? new Date(article.published_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })
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
                    {article.description && (
                      <span className="article-desc">{article.description}</span>
                    )}
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

      {activeItem && (
        <InsightDrillModal
          open
          kind={activeItem.kind}
          heading={activeItem.heading}
          summary={activeItem.summary}
          sources={activeSources}
          expanded={activeExpanded}
          deepExpanded={activeDeep}
          loading={expandLoading}
          deepLoading={deepLoading}
          error={expandError}
          onAskMore={() => void askMore(activeItem.kind, activeItem.index)}
          onAskDeep={() => void askDeep(activeItem.kind, activeItem.index)}
          onClose={closeDrill}
        />
      )}
    </article>
  )
}

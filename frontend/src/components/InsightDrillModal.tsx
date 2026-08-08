import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { ExpandInsightKind, ExpandInsightResult, NewsArticle } from '../types'

interface Props {
  open: boolean
  kind: ExpandInsightKind
  heading: string
  summary: string
  sources: NewsArticle[]
  expanded: ExpandInsightResult | null
  deepExpanded: ExpandInsightResult | null
  loading: boolean
  deepLoading: boolean
  error: string | null
  onAskMore: () => void
  onAskDeep: () => void
  onClose: () => void
}

const KIND_LABEL: Record<ExpandInsightKind, string> = {
  opportunity: 'Opportunity',
  risk: 'Risk',
  recommendation: 'Recommendation',
}

export function InsightDrillModal({
  open,
  kind,
  heading,
  summary,
  sources,
  expanded,
  deepExpanded,
  loading,
  deepLoading,
  error,
  onAskMore,
  onAskDeep,
  onClose,
}: Props) {
  const expandRef = useRef<HTMLElement | null>(null)
  const deepRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open, onClose])

  useEffect(() => {
    if (!expanded || !expandRef.current) return
    expandRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [expanded])

  useEffect(() => {
    if (!deepExpanded || !deepRef.current) return
    deepRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [deepExpanded])

  if (!open) return null

  return createPortal(
    <div className="insight-modal-root" role="presentation">
      <button
        type="button"
        className="insight-modal-backdrop"
        aria-label="Close dig-deeper popup"
        onClick={onClose}
      />
      <div
        className="insight-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="insight-modal-title"
      >
        <header className="insight-modal-header">
          <div>
            <p className="section-label">{KIND_LABEL[kind]}</p>
            <h2 id="insight-modal-title">{heading}</h2>
          </div>
          <button type="button" className="insight-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className="insight-modal-body">
          <p className="insight-modal-summary">{summary}</p>

          <section className="insight-modal-section">
            <div className="insight-modal-section-head">
              <p className="subsection-label">Source story</p>
              <span className="insight-count-pill">{sources.length} linked</span>
            </div>
            {sources.length === 0 ? (
              <p className="empty-hint">No linked source articles found for this item yet.</p>
            ) : (
              <ul className="insight-source-list">
                {sources.map((article, index) => {
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
                      <span className="insight-source-index" aria-hidden="true">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      <span className="insight-source-copy">
                        <strong>{article.title}</strong>
                        {article.description && <span>{article.description}</span>}
                        {meta && <em>{meta}</em>}
                      </span>
                    </>
                  )
                  return (
                    <li key={`${article.title}-${index}`}>
                      {article.url ? (
                        <a href={article.url} target="_blank" rel="noopener noreferrer">
                          {body}
                        </a>
                      ) : (
                        <div>{body}</div>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          <div className="insight-drill-actions">
            <button
              type="button"
              className="btn insight-more-btn"
              onClick={onAskMore}
              disabled={loading || Boolean(expanded)}
            >
              {loading
                ? 'Dig-deeper agent working…'
                : expanded
                  ? 'More info loaded'
                  : 'Give me more info on this'}
            </button>
          </div>

          {error && <p className="email-status error">{error}</p>}

          {loading && !expanded && (
            <div className="insight-modal-loading" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <span>Gathering a deeper brief on this story…</span>
            </div>
          )}

          {expanded && (
            <section className="insight-expand-result" ref={expandRef}>
              <div className="insight-expand-head">
                <div>
                  <p className="subsection-label">Dig-deeper agent</p>
                  <h3>Deeper read on this story</h3>
                </div>
                {expanded.fallback && <span className="insight-expand-badge">Fallback</span>}
              </div>

              <div className="insight-expand-grid">
                <article className="insight-expand-hero">
                  <p className="insight-expand-kicker">Analysis</p>
                  <p className="insight-expand-body">{expanded.deeper_analysis}</p>
                </article>

                {expanded.why_it_matters && (
                  <article className="insight-expand-card insight-expand-card--accent">
                    <p className="insight-expand-kicker">Why it matters</p>
                    <p>{expanded.why_it_matters}</p>
                  </article>
                )}

                {expanded.questions_to_ask.length > 0 && (
                  <article className="insight-expand-card">
                    <p className="insight-expand-kicker">Questions to ask</p>
                    <ol className="insight-expand-steps">
                      {expanded.questions_to_ask.map((question, index) => (
                        <li key={question}>
                          <span aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                          <p>{question}</p>
                        </li>
                      ))}
                    </ol>
                  </article>
                )}

                {expanded.suggested_moves.length > 0 && (
                  <article className="insight-expand-card">
                    <p className="insight-expand-kicker">Suggested moves</p>
                    <ol className="insight-expand-steps">
                      {expanded.suggested_moves.map((move, index) => (
                        <li key={move}>
                          <span aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                          <p>{move}</p>
                        </li>
                      ))}
                    </ol>
                  </article>
                )}
              </div>

              <div className="insight-deep-cta">
                <p className="insight-deep-cta-copy">
                  Still unclear? Ask the deep-dive agent for a slower, more verbose explanation with
                  the key points highlighted.
                </p>
                <button
                  type="button"
                  className="btn btn-secondary insight-more-btn"
                  onClick={onAskDeep}
                  disabled={deepLoading || Boolean(deepExpanded)}
                >
                  {deepLoading
                    ? 'Deep-dive agent working…'
                    : deepExpanded
                      ? 'Deep dive loaded'
                      : 'Dig deeper again — more detail'}
                </button>
              </div>

              {deepLoading && !deepExpanded && (
                <div className="insight-modal-loading" role="status" aria-live="polite">
                  <span className="spinner" aria-hidden="true" />
                  <span>Unpacking the story in more detail…</span>
                </div>
              )}

              {deepExpanded && (
                <section className="insight-deep-result" ref={deepRef}>
                  <div className="insight-expand-head">
                    <div>
                      <p className="subsection-label">Deep-dive agent</p>
                      <h3>Verbose walkthrough</h3>
                    </div>
                    {deepExpanded.fallback && (
                      <span className="insight-expand-badge">Fallback</span>
                    )}
                  </div>

                  <article className="insight-deep-narrative">
                    <p className="insight-expand-kicker">Full explanation</p>
                    <p>
                      {deepExpanded.detailed_narrative || deepExpanded.deeper_analysis}
                    </p>
                  </article>

                  {(deepExpanded.spotlight_points || []).length > 0 && (
                    <div className="insight-spotlight">
                      <p className="insight-expand-kicker">Points to notice</p>
                      <ul className="insight-spotlight-list">
                        {(deepExpanded.spotlight_points || []).map((item) => (
                          <li key={`${item.point}-${item.explanation}`}>
                            <strong className="insight-spotlight-point">{item.point}</strong>
                            <span>{item.explanation}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </section>
              )}
            </section>
          )}
        </div>
      </div>
    </div>,
    document.body,
  )
}

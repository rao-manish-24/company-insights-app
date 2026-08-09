import { useState } from 'react'
import type { AnalysisListItem, CompanyAnalysis } from '../types'

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

interface Props {
  recent: AnalysisListItem[]
  analysis: CompanyAnalysis | null
  historyError: string | null
  historyLoading: boolean
  historyLoaded: boolean
  loading: boolean
  onLoadHistory: () => void | Promise<unknown>
  onClearHistory: () => void | Promise<unknown>
  onOpenRecent: (id: number) => void | Promise<unknown>
  /** Home: show expand/collapse. Insights: always open. */
  collapsible?: boolean
  defaultExpanded?: boolean
  className?: string
}

export function BriefLibrary({
  recent,
  analysis,
  historyError,
  historyLoading,
  historyLoaded,
  loading,
  onLoadHistory,
  onClearHistory,
  onOpenRecent,
  collapsible = false,
  defaultExpanded = true,
  className,
}: Props) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const showBody = !collapsible || expanded
  const lead = historyLoaded
    ? recent.length > 0
      ? `${recent.length} brief${recent.length === 1 ? '' : 's'} ready to reopen.`
      : 'No saved briefs yet.'
    : 'Load your previous searches.'

  return (
    <aside
      className={`workspace-aside${collapsible ? ' workspace-aside--home' : ''}${
        collapsible && !expanded ? ' is-collapsed' : ''
      }${className ? ` ${className}` : ''}`}
    >
      <div className="aside-head">
        {collapsible ? (
          <button
            type="button"
            className="library-collapse-toggle"
            aria-expanded={expanded}
            aria-controls="brief-library-body"
            onClick={() => setExpanded((value) => !value)}
          >
            <span className="library-collapse-copy">
              <p className="section-label">Library</p>
              <h2>Recent briefs</h2>
              <p className="aside-lead">{lead}</p>
            </span>
            <span className="library-collapse-end" aria-hidden="true">
              <span className="library-collapse-label">{expanded ? 'Collapse' : 'Expand'}</span>
              <span className={`library-collapse-chevron${expanded ? ' is-open' : ''}`} />
            </span>
          </button>
        ) : (
          <>
            <p className="section-label">Library</p>
            <h2>Recent briefs</h2>
            <p className="aside-lead">{lead}</p>
          </>
        )}
      </div>

      {showBody && (
        <div id="brief-library-body" className="library-body">
          <div className="library-actions">
            <button
              type="button"
              className="btn btn-secondary library-btn"
              onClick={() => void onLoadHistory()}
              disabled={loading || historyLoading}
            >
              {historyLoading ? 'Loading…' : 'Last 15'}
            </button>
            <button
              type="button"
              className="btn btn-ghost library-btn"
              onClick={() => void onClearHistory()}
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
        </div>
      )}
    </aside>
  )
}

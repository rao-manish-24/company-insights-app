import { useEffect, useMemo, useState } from 'react'
import type { AnalysisRunMetrics } from '../types'

const STAGES = [
  { id: 'news', label: 'News intake', detail: 'Pulling recent coverage', start: 0, end: 18 },
  {
    id: 'profile',
    label: 'Company snapshot',
    detail: 'Profile, leadership, and market data',
    start: 18,
    end: 40,
  },
  {
    id: 'llm',
    label: 'Insight agent',
    detail: 'Drafting themes, risks, and recommendations',
    start: 40,
    end: 88,
  },
  { id: 'save', label: 'Saving brief', detail: 'Persisting the partner-ready brief', start: 88, end: 97 },
] as const

/** Rough English equivalence: ~0.75 words per token. */
function approxWords(tokens: number | null | undefined) {
  if (tokens == null || tokens <= 0) return null
  return Math.round(tokens * 0.75)
}

function formatElapsed(ms: number) {
  const totalSeconds = Math.max(0, ms / 1000)
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds - minutes * 60
  return `${minutes}m ${seconds.toFixed(1)}s`
}

function formatTokens(value: number | null | undefined) {
  if (value == null) return '—'
  return value.toLocaleString()
}

function formatWords(tokens: number | null | undefined) {
  const words = approxWords(tokens)
  if (words == null) return null
  return `~${words.toLocaleString()} words`
}

interface Props {
  active: boolean
  mode?: 'analyze' | 'open'
  metrics: AnalysisRunMetrics | null
}

export function AnalysisProgress({ active, mode = 'analyze', metrics }: Props) {
  const [now, setNow] = useState(() => Date.now())
  const [startedAt, setStartedAt] = useState<number | null>(null)

  useEffect(() => {
    if (!active) {
      setStartedAt(null)
      return
    }
    const start = Date.now()
    setStartedAt(start)
    setNow(start)
    const timer = window.setInterval(() => setNow(Date.now()), 100)
    return () => window.clearInterval(timer)
  }, [active])

  const elapsedMs = active && startedAt ? now - startedAt : metrics?.elapsedMs || 0

  const percent = useMemo(() => {
    if (!active) return metrics ? 100 : 0
    if (mode === 'open') {
      return Math.min(92, 20 + elapsedMs / 40)
    }

    // Stage-aware progress that asymptotes under 97% until the API returns.
    const seconds = elapsedMs / 1000
    if (seconds < 4) return 6 + (seconds / 4) * 12
    if (seconds < 10) return 18 + ((seconds - 4) / 6) * 22
    if (seconds < 28) return 40 + ((seconds - 10) / 18) * 42
    if (seconds < 55) return 82 + ((seconds - 28) / 27) * 12
    return 95
  }, [active, elapsedMs, metrics, mode])

  const displayPercent = Math.round(Math.min(100, Math.max(0, percent)))
  const currentStage =
    STAGES.find((stage) => displayPercent >= stage.start && displayPercent < stage.end) ||
    STAGES[STAGES.length - 1]

  const showUsageDetail = !active && Boolean(metrics) && mode === 'analyze'
  const cached = Boolean(metrics?.cached)
  const promptTokens = cached ? 0 : metrics?.promptTokens ?? null
  const completionTokens = cached ? 0 : metrics?.completionTokens ?? null
  const totalTokens = cached ? 0 : metrics?.totalTokens ?? null
  const promptShare =
    totalTokens && totalTokens > 0 && promptTokens != null
      ? Math.round((promptTokens / totalTokens) * 100)
      : 0
  const completionShare = totalTokens && totalTokens > 0 ? 100 - promptShare : 0

  if (!active && !metrics) return null

  return (
    <div className={`analysis-progress ${active ? 'is-active' : 'is-complete'}`} role="status" aria-live="polite">
      <div className="analysis-progress-top">
        <div className="analysis-progress-title-row">
          <span className="analysis-progress-ring" aria-hidden="true">
            <span className="analysis-progress-ring-core" />
          </span>
          <div>
            <strong>
              {active
                ? mode === 'open'
                  ? 'Opening brief'
                  : 'Building the brief'
                : 'Brief ready'}
            </strong>
            <span>
              {active
                ? mode === 'open'
                  ? 'Fetching the saved analysis from the library…'
                  : `${currentStage.label} — ${currentStage.detail}`
                : cached
                  ? 'Served from cache — no new model tokens were used.'
                  : 'Pipeline finished. Timing and token usage below.'}
            </span>
          </div>
        </div>
        <div className="analysis-progress-percent" aria-hidden={!active && !metrics}>
          <em>{displayPercent}</em>
          <span>%</span>
        </div>
      </div>

      <div
        className="analysis-progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={displayPercent}
        aria-label="Analysis progress"
      >
        <div className="analysis-progress-fill" style={{ width: `${displayPercent}%` }} />
      </div>

      {mode === 'analyze' && (
        <ol className="analysis-progress-stages">
          {STAGES.map((stage) => {
            const done = displayPercent >= stage.end || (!active && Boolean(metrics))
            const current = active && currentStage.id === stage.id
            return (
              <li
                key={stage.id}
                className={`${done ? 'is-done' : ''} ${current ? 'is-current' : ''}`}
              >
                <span className="analysis-stage-dot" aria-hidden="true" />
                <span>{stage.label}</span>
              </li>
            )
          })}
        </ol>
      )}

      <div className="analysis-progress-stats">
        <div>
          <span className="analysis-stat-label">Elapsed</span>
          <strong>{formatElapsed(elapsedMs)}</strong>
          <small>Wall time to finish this run</small>
        </div>
        <div>
          <span className="analysis-stat-label">Total tokens</span>
          <strong>
            {active ? 'Counting…' : cached ? '0 (cached)' : formatTokens(totalTokens)}
          </strong>
          <small>
            {active
              ? 'Prompt + completion once the model finishes'
              : cached
                ? 'No LLM call — reused saved brief'
                : formatWords(totalTokens)
                  ? `${formatWords(totalTokens)} processed overall`
                  : 'Prompt + completion for this LLM call'}
          </small>
        </div>
        <div>
          <span className="analysis-stat-label">Prompt</span>
          <strong>
            {active ? '—' : cached ? '0' : formatTokens(promptTokens)}
          </strong>
          <small>
            {active
              ? 'Input sent to the model'
              : cached
                ? 'No new input tokens'
                : formatWords(promptTokens)
                  ? `${formatWords(promptTokens)} of instructions + news context`
                  : 'Input: instructions, news, company context'}
          </small>
        </div>
        <div>
          <span className="analysis-stat-label">Completion</span>
          <strong>
            {active ? '—' : cached ? '0' : formatTokens(completionTokens)}
          </strong>
          <small>
            {active
              ? 'Output the model writes back'
              : cached
                ? 'No new output tokens'
                : formatWords(completionTokens)
                  ? `${formatWords(completionTokens)} of brief content generated`
                  : 'Output: summary, themes, risks, actions'}
          </small>
        </div>
      </div>

      {showUsageDetail && (
        <div className="analysis-token-detail">
          <div className="analysis-token-detail-head">
            <strong>Token usage explained</strong>
            <span>
              A token is a word piece the model reads or writes — roughly ¾ of an English word.
            </span>
          </div>

          {!cached && totalTokens != null && totalTokens > 0 ? (
            <>
              <div
                className="analysis-token-split"
                role="img"
                aria-label={`Prompt ${promptShare} percent, completion ${completionShare} percent`}
              >
                <span className="analysis-token-split-prompt" style={{ width: `${promptShare}%` }} />
                <span
                  className="analysis-token-split-completion"
                  style={{ width: `${completionShare}%` }}
                />
              </div>
              <ul className="analysis-token-legend">
                <li>
                  <span className="swatch swatch-prompt" aria-hidden="true" />
                  <div>
                    <strong>
                      Prompt · {formatTokens(promptTokens)} tokens ({promptShare}%)
                    </strong>
                    <span>
                      What the model received: system rules, company name, recent articles, and
                      profile/market context.
                    </span>
                  </div>
                </li>
                <li>
                  <span className="swatch swatch-completion" aria-hidden="true" />
                  <div>
                    <strong>
                      Completion · {formatTokens(completionTokens)} tokens ({completionShare}%)
                    </strong>
                    <span>
                      What the model generated: executive summary, themes, opportunities, risks,
                      recommendations, and conversation starters.
                    </span>
                  </div>
                </li>
                <li>
                  <span className="swatch swatch-total" aria-hidden="true" />
                  <div>
                    <strong>Total · {formatTokens(totalTokens)} tokens</strong>
                    <span>
                      Prompt + completion for this analyze call
                      {formatWords(totalTokens) ? ` (${formatWords(totalTokens)} equivalent)` : ''}.
                      Higher totals usually mean richer news context or a longer brief.
                    </span>
                  </div>
                </li>
              </ul>
            </>
          ) : (
            <p className="analysis-token-cached-note">
              This response came from cache, so the insight agent did not run again and token usage
              stayed at zero. Use Refresh to pull a new brief and spend new tokens.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

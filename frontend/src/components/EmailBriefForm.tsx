import { useState, type FormEvent } from 'react'
import { emailAnalysis } from '../api'

interface Props {
  analysisId: number
}

export function EmailBriefForm({ analysisId }: Props) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    setStatus(null)
    setError(null)
    try {
      const result = await emailAnalysis(analysisId, email.trim() || undefined)
      setStatus(`Sent to ${result.to}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send email')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="email-form">
      <div className="brief-section-head">
        <p className="section-label">Share</p>
        <h2>Send to inbox</h2>
      </div>
      <p className="email-hint">
        Email Company Insights brief to yourself. Leave blank to use the default email address set.
      </p>
      <form className="email-row" onSubmit={onSubmit}>
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="Leave blank for default address, or type an email"
          aria-label="Email address for this brief"
          disabled={sending}
        />
        <button className="btn" type="submit" disabled={sending}>
          {sending ? 'Sending…' : 'Email brief'}
        </button>
      </form>
      <div aria-live="polite">
        {status && <p className="email-status ok">{status}</p>}
        {error && <p className="email-status error">{error}</p>}
      </div>
    </div>
  )
}

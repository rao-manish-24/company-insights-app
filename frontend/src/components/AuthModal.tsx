import { type FormEvent, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useAuth } from '../hooks/useAuth'

export function AuthModal() {
  const { authOpen, authMode, authMessage, closeAuth, signIn, register, openAuth } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!authOpen) return
    setError(null)
    setPassword('')
  }, [authOpen, authMode])

  useEffect(() => {
    if (!authOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeAuth()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [authOpen, closeAuth])

  if (!authOpen) return null

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (authMode === 'signin') {
        await signIn(email.trim(), password)
      } else {
        await register(email.trim(), password, displayName)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed')
    } finally {
      setSubmitting(false)
    }
  }

  return createPortal(
    <div className="auth-modal-root" role="presentation" onClick={closeAuth}>
      <div
        className="auth-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="auth-modal-head">
          <div>
            <p className="section-label">Account</p>
            <h2 id="auth-modal-title">
              {authMode === 'signin' ? 'Sign in to continue' : 'Create your account'}
            </h2>
            <p className="auth-modal-lead">
              {authMessage ||
                (authMode === 'signin'
                  ? 'Sign in to generate briefs and keep them in your private library.'
                  : 'Register to save partner briefs under your email.')}
            </p>
          </div>
          <button type="button" className="btn btn-ghost auth-close" onClick={closeAuth}>
            Close
          </button>
        </div>

        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={authMode === 'signin'}
            className={authMode === 'signin' ? 'is-active' : ''}
            onClick={() => openAuth({ mode: 'signin', message: authMessage || undefined })}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={authMode === 'register'}
            className={authMode === 'register' ? 'is-active' : ''}
            onClick={() => openAuth({ mode: 'register', message: authMessage || undefined })}
          >
            Create account
          </button>
        </div>

        <form className="auth-form" onSubmit={onSubmit}>
          {authMode === 'register' && (
            <label className="auth-field">
              <span>Display name</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                autoComplete="name"
                placeholder="Optional"
              />
            </label>
          )}
          <label className="auth-field">
            <span>{authMode === 'signin' ? 'Email or username' : 'Email'}</span>
            <input
              type={authMode === 'signin' ? 'text' : 'email'}
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete={authMode === 'signin' ? 'username' : 'email'}
              placeholder={authMode === 'signin' ? 'admin or you@firm.com' : 'you@firm.com'}
            />
          </label>
          <label className="auth-field">
            <span>Password</span>
            <input
              type="password"
              required
              minLength={authMode === 'register' ? 8 : 1}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={authMode === 'signin' ? 'current-password' : 'new-password'}
              placeholder={authMode === 'register' ? 'At least 8 characters' : 'Your password'}
            />
          </label>

          {error && <p className="auth-error">{error}</p>}

          <button className="btn auth-submit" type="submit" disabled={submitting || !email.trim()}>
            {submitting
              ? 'Please wait…'
              : authMode === 'signin'
                ? 'Sign in'
                : 'Create account'}
          </button>
        </form>
      </div>
    </div>,
    document.body,
  )
}

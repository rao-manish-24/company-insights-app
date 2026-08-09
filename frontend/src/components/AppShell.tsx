import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { AuthModal } from './AuthModal'

export function AppShell() {
  const { user, ready, openAuth, signOut } = useAuth()

  return (
    <div className="app app--routed">
      <div className="atmosphere" aria-hidden="true">
        <div className="atmosphere-grid" />
        <div className="atmosphere-glow atmosphere-glow--a" />
        <div className="atmosphere-glow atmosphere-glow--b" />
        <div className="atmosphere-ring" />
      </div>

      <div className="app-shell">
        <header className="topbar">
          <Link className="brand-mark" to="/" aria-label="Company Insights home">
            <span className="brand-mark-icon" aria-hidden="true">
              <span className="brand-mark-core" />
            </span>
            <span className="brand-word">Company Insights</span>
          </Link>
          <div className="topbar-actions">
            <span className="topbar-note">Home search → /insights brief</span>
            {ready && user ? (
              <div className="topbar-user">
                <Link className="btn btn-ghost topbar-auth-btn" to="/">
                  Home
                </Link>
                <Link className="btn btn-ghost topbar-auth-btn" to="/insights">
                  Insights
                </Link>
                <span
                  className={`topbar-user-email${user.is_guest ? ' is-guest' : ''}`}
                  title={user.is_guest ? 'Private session — not linked to an email' : user.email}
                >
                  {user.is_guest ? 'Private' : user.display_name || user.email}
                </span>
                <button type="button" className="btn btn-ghost topbar-auth-btn" onClick={signOut}>
                  {user.is_guest ? 'End session' : 'Sign out'}
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

        <Outlet />
      </div>

      <AuthModal />
    </div>
  )
}

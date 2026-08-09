import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { fetchMe, loginAccount, registerAccount, startGuestSession } from '../api'
import { clearAuthToken, getAuthToken, setAuthToken } from '../auth'
import type { UserPublic } from '../types'

type AuthMode = 'signin' | 'register'

interface AuthContextValue {
  user: UserPublic | null
  ready: boolean
  authOpen: boolean
  authMode: AuthMode
  authMessage: string | null
  pendingCompany: string | null
  openAuth: (opts?: { mode?: AuthMode; message?: string; pendingCompany?: string }) => void
  closeAuth: () => void
  signIn: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName?: string) => Promise<void>
  /** Reuse a valid guest token when possible; otherwise mint a short-lived private session. */
  continuePrivately: () => Promise<UserPublic>
  signOut: () => void
  clearPendingCompany: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null)
  const [ready, setReady] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<AuthMode>('signin')
  const [authMessage, setAuthMessage] = useState<string | null>(null)
  const [pendingCompany, setPendingCompany] = useState<string | null>(null)
  const guestBootRef = useRef<Promise<UserPublic> | null>(null)
  const sessionGenRef = useRef(0)
  const userRef = useRef<UserPublic | null>(null)
  userRef.current = user

  useEffect(() => {
    const token = getAuthToken()
    if (!token) {
      setReady(true)
      return
    }
    let cancelled = false
    void fetchMe()
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch(() => {
        clearAuthToken()
        if (!cancelled) setUser(null)
      })
      .finally(() => {
        if (!cancelled) setReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const openAuth = useCallback(
    (opts?: { mode?: AuthMode; message?: string; pendingCompany?: string }) => {
      setAuthMode(opts?.mode || 'signin')
      setAuthMessage(opts?.message || null)
      if (opts?.pendingCompany != null) setPendingCompany(opts.pendingCompany)
      setAuthOpen(true)
    },
    [],
  )

  const closeAuth = useCallback(() => {
    setAuthOpen(false)
    setAuthMessage(null)
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await loginAccount({ email, password })
    setAuthToken(result.access_token)
    setUser(result.user)
    setAuthOpen(false)
    setAuthMessage(null)
  }, [])

  const register = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const result = await registerAccount({
        email,
        password,
        display_name: displayName?.trim() || undefined,
      })
      setAuthToken(result.access_token)
      setUser(result.user)
      setAuthOpen(false)
      setAuthMessage(null)
    },
    [],
  )

  const continuePrivately = useCallback(async (): Promise<UserPublic> => {
    const current = userRef.current
    if (current) return current
    if (guestBootRef.current) return guestBootRef.current

    const gen = sessionGenRef.current
    const boot = (async () => {
      const existing = getAuthToken()
      if (existing) {
        try {
          const me = await fetchMe()
          if (gen !== sessionGenRef.current) {
            throw new Error('Session ended')
          }
          setUser(me)
          setAuthOpen(false)
          setAuthMessage(null)
          return me
        } catch (err) {
          if (gen !== sessionGenRef.current) throw err
          clearAuthToken()
        }
      }

      const result = await startGuestSession()
      if (gen !== sessionGenRef.current) {
        throw new Error('Session ended')
      }
      setAuthToken(result.access_token)
      setUser(result.user)
      setAuthOpen(false)
      setAuthMessage(null)
      return result.user
    })()

    guestBootRef.current = boot
    try {
      return await boot
    } finally {
      if (guestBootRef.current === boot) guestBootRef.current = null
    }
  }, [])

  const signOut = useCallback(() => {
    // Invalidate any in-flight private-session boot so it can't resurrect the user.
    sessionGenRef.current += 1
    guestBootRef.current = null
    clearAuthToken()
    setUser(null)
    setPendingCompany(null)
    setAuthOpen(false)
    setAuthMessage(null)
  }, [])

  const clearPendingCompany = useCallback(() => setPendingCompany(null), [])

  const value = useMemo(
    () => ({
      user,
      ready,
      authOpen,
      authMode,
      authMessage,
      pendingCompany,
      openAuth,
      closeAuth,
      signIn,
      register,
      continuePrivately,
      signOut,
      clearPendingCompany,
    }),
    [
      user,
      ready,
      authOpen,
      authMode,
      authMessage,
      pendingCompany,
      openAuth,
      closeAuth,
      signIn,
      register,
      continuePrivately,
      signOut,
      clearPendingCompany,
    ],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { fetchMe, loginAccount, registerAccount } from '../api'
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

  const signOut = useCallback(() => {
    clearAuthToken()
    setUser(null)
    setPendingCompany(null)
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

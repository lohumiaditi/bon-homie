/**
 * AuthContext — manages Facebook login state across the whole app.
 *
 * Usage:
 *   const { user, loading, login, logout } = useAuth()
 *
 * `user` is null when logged out, or { user_id, name, email, picture_url } when logged in.
 * JWT is stored in an HTTP-only cookie (invisible to JS — XSS-safe).
 * This context just calls /auth/me to check if the cookie is valid.
 */

import { createContext, useContext, useEffect, useState, useCallback } from 'react'

const AuthContext = createContext(null)

const API = '/api'

export function AuthProvider({ children }) {
  const [user, setUser]     = useState(null)   // null = logged out / unknown
  const [loading, setLoading] = useState(true)  // true during initial check

  // On mount: silently check if we already have a valid session cookie
  const checkSession = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/auth/me`, { credentials: 'include' })
      if (res.ok) {
        setUser(await res.json())
      } else if (res.status === 401) {
        // Try silent refresh first
        const refreshRes = await fetch(`${API}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        })
        if (refreshRes.ok) {
          const meRes = await fetch(`${API}/auth/me`, { credentials: 'include' })
          setUser(meRes.ok ? await meRes.json() : null)
        } else {
          setUser(null)
        }
      }
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // Check for ?auth=success or ?auth_error in URL after OAuth redirect
    const params = new URLSearchParams(window.location.search)
    if (params.has('auth') || params.has('auth_error')) {
      // Clean the URL
      window.history.replaceState({}, '', window.location.pathname)
    }
    checkSession()
  }, [checkSession])

  // Redirect to backend OAuth route (server handles FB redirect + state cookie)
  const login = () => {
    window.location.href = `${API}/auth/facebook`
  }

  const logout = async () => {
    await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'include' })
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, checkSession }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

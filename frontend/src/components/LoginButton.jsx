/**
 * LoginButton — Facebook JS SDK login (popup-based, no redirect URI needed).
 *
 * How it works:
 *   1. FB JS SDK opens a popup — user approves
 *   2. SDK returns an access_token to THIS page
 *   3. We POST it to /auth/facebook/token
 *   4. Backend verifies with Facebook, creates user, sets HTTP-only JWT cookie
 *   5. AuthContext detects the cookie and marks user as logged in
 *
 * This works on ANY localhost port — no redirect URI config needed.
 */

import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'

const FB_BLUE   = '#1877F2'
const APP_ID    = import.meta.env.VITE_FB_APP_ID   // set in frontend/.env

// Load the Facebook JS SDK once
function loadFBSdk(appId) {
  if (window.FB) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Facebook SDK timed out. Check your internet connection.')), 10_000)
    window.fbAsyncInit = () => {
      clearTimeout(timer)
      window.FB.init({ appId, cookie: false, xfbml: false, version: 'v19.0' })
      resolve()
    }
    const s = document.createElement('script')
    s.src = 'https://connect.facebook.net/en_US/sdk.js'
    s.async = true
    s.defer = true
    s.onerror = () => { clearTimeout(timer); reject(new Error('Failed to load Facebook SDK.')) }
    document.body.appendChild(s)
  })
}

export default function LoginButton() {
  const { user, loading, checkSession, logout } = useAuth()
  const [menuOpen,  setMenuOpen]  = useState(false)
  const [signing,   setSigning]   = useState(false)
  const [error,     setError]     = useState('')

  useEffect(() => { if (APP_ID) loadFBSdk(APP_ID) }, [])

  async function handleFBLogin() {
    if (!APP_ID) {
      setError('VITE_FB_APP_ID not set in frontend/.env')
      return
    }
    setSigning(true)
    setError('')
    try {
      await loadFBSdk(APP_ID)

      // Open FB popup — request email + public_profile
      const authResp = await new Promise((resolve, reject) =>
        window.FB.login(resp => {
          if (resp.authResponse) resolve(resp.authResponse)
          else reject(new Error(resp.status === 'not_authorized'
            ? 'You declined the Facebook permission request.'
            : 'Facebook login popup was closed.'))
        }, { scope: 'public_profile' })
      )

      // Send access token to our backend for secure verification
      const res = await fetch('/api/auth/facebook/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ access_token: authResp.accessToken }),
      })

      if (!res.ok) {
        let detail = `Server error (${res.status})`
        try { detail = (await res.json()).detail || detail } catch {}
        throw new Error(detail)
      }

      // Backend set the JWT cookie — refresh auth state
      await checkSession()
    } catch (e) {
      setError(e.message || 'Login failed. Please try again.')
    } finally {
      setSigning(false)
    }
  }

  if (loading) return <div className="w-36 h-9 rounded-lg bg-gray-100 animate-pulse" />

  // ── Logged in ──────────────────────────────────────────────────────────
  if (user) {
    return (
      <div className="relative">
        <button
          onClick={() => setMenuOpen(o => !o)}
          className="flex items-center gap-2 rounded-full pr-3 pl-1 py-1 hover:bg-gray-100 transition"
        >
          {user.picture_url
            ? <img src={user.picture_url} alt={user.name}
                className="w-8 h-8 rounded-full border border-gray-200 object-cover" />
            : <div className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center text-sm font-bold">
                {(user.name || 'U')[0].toUpperCase()}
              </div>
          }
          <span className="text-sm font-medium text-gray-700 max-w-[120px] truncate">
            {user.name || 'My Account'}
          </span>
          <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 mt-2 w-52 bg-white rounded-xl shadow-lg border border-gray-100 z-20 py-2">
              <div className="px-4 py-2 border-b border-gray-50">
                <p className="text-sm font-semibold text-gray-800 truncate">{user.name}</p>
                {user.email && <p className="text-xs text-gray-400 truncate">{user.email}</p>}
              </div>
              <div className="px-2 pt-1">
                <div className="flex items-center gap-2 px-3 py-1.5">
                  <span className="text-green-500 text-xs">🔒</span>
                  <span className="text-xs text-gray-500">Data encrypted at rest</span>
                </div>
              </div>
              <div className="px-2">
                <button onClick={() => { setMenuOpen(false); logout() }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-red-600 hover:bg-red-50 transition">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                  </svg>
                  Sign out
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    )
  }

  // ── Logged out ─────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col items-center gap-2">
      <button
        onClick={handleFBLogin}
        disabled={signing}
        className="flex items-center gap-2.5 px-4 py-2 rounded-lg text-white text-sm font-semibold shadow-sm hover:brightness-110 active:scale-95 transition disabled:opacity-60"
        style={{ backgroundColor: FB_BLUE }}
      >
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
          <path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.267h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/>
        </svg>
        {signing ? 'Connecting…' : 'Continue with Facebook'}
      </button>
      {error && <p className="text-xs text-red-500 max-w-xs text-center">{error}</p>}
    </div>
  )
}

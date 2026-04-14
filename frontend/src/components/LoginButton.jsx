/**
 * LoginButton — Facebook OAuth login / user avatar dropdown.
 *
 * Shows a "Continue with Facebook" button when logged out.
 * Shows a user avatar + name + logout option when logged in.
 */

import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'

// Official Facebook blue
const FB_BLUE = '#1877F2'

export default function LoginButton() {
  const { user, loading, login, logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)

  if (loading) {
    return (
      <div className="w-36 h-9 rounded-lg bg-gray-100 animate-pulse" />
    )
  }

  // ── Logged in: show avatar + name + dropdown ────────────────────────────
  if (user) {
    return (
      <div className="relative">
        <button
          onClick={() => setMenuOpen(o => !o)}
          className="flex items-center gap-2 rounded-full pr-3 pl-1 py-1 hover:bg-gray-100 transition"
          aria-label="Account menu"
        >
          {user.picture_url ? (
            <img
              src={user.picture_url}
              alt={user.name}
              className="w-8 h-8 rounded-full border border-gray-200 object-cover"
            />
          ) : (
            <div className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center text-sm font-bold">
              {(user.name || 'U')[0].toUpperCase()}
            </div>
          )}
          <span className="text-sm font-medium text-gray-700 max-w-[120px] truncate">
            {user.name || 'My Account'}
          </span>
          <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {menuOpen && (
          <>
            {/* Backdrop */}
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            {/* Dropdown */}
            <div className="absolute right-0 mt-2 w-52 bg-white rounded-xl shadow-lg border border-gray-100 z-20 py-2">
              <div className="px-4 py-2 border-b border-gray-50">
                <p className="text-sm font-semibold text-gray-800 truncate">{user.name}</p>
                {user.email && (
                  <p className="text-xs text-gray-400 truncate">{user.email}</p>
                )}
              </div>

              <div className="px-2 py-1">
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg">
                  <svg className="w-3.5 h-3.5 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clipRule="evenodd" />
                  </svg>
                  <span className="text-xs text-gray-500">End-to-end encrypted</span>
                </div>
              </div>

              <div className="px-2">
                <button
                  onClick={() => { setMenuOpen(false); logout() }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-red-600 hover:bg-red-50 transition"
                >
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

  // ── Logged out: show Facebook login button ───────────────────────────────
  return (
    <button
      onClick={login}
      className="flex items-center gap-2.5 px-4 py-2 rounded-lg text-white text-sm font-semibold shadow-sm hover:brightness-110 active:scale-95 transition"
      style={{ backgroundColor: FB_BLUE }}
    >
      {/* Official Facebook "f" logo */}
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
        <path d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.513c-1.491 0-1.956.93-1.956 1.886v2.267h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z"/>
      </svg>
      Continue with Facebook
    </button>
  )
}

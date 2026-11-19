import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { useAuth } from '../state/AuthContext'
import './integration-foundation.css'

function ThemeParticles() {
  return (
    <div className="integration-particles" aria-hidden="true">
      {Array.from({ length: 18 }, (_, index) => (
        <span
          className="integration-particle"
          key={index}
          style={{
            '--x': `${(index * 37 + 11) % 100}%`,
            '--y': `${(index * 53 + 7) % 100}%`,
            '--size': `${3 + (index % 4) * 2}px`,
            '--duration': `${7 + (index % 5) * 1.7}s`,
            '--delay': `${-((index * 3) % 12)}s`,
          } as React.CSSProperties}
        />
      ))}
    </div>
  )
}

export function IntegrationLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout } = useAuth()
  const isIndividualChat = location.pathname.startsWith('/conversations/') && location.pathname !== '/conversations'
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false)

  // Close drawer upon navigation
  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  // Support Escape key to close drawer or logout dialog
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        if (showLogoutConfirm) {
          setShowLogoutConfirm(false)
        } else if (drawerOpen) {
          setDrawerOpen(false)
        }
      }
    }
    if (drawerOpen || showLogoutConfirm) {
      window.addEventListener('keydown', onKeyDown)
      return () => window.removeEventListener('keydown', onKeyDown)
    }
  }, [drawerOpen, showLogoutConfirm])

  // Prevent background scrolling while drawer or logout dialog is open
  useEffect(() => {
    if (drawerOpen || showLogoutConfirm) {
      const originalOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => {
        document.body.style.overflow = originalOverflow
      }
    }
  }, [drawerOpen, showLogoutConfirm])

  function handleLogoutConfirm() {
    setShowLogoutConfirm(false)
    setDrawerOpen(false)
    logout()
    navigate('/login')
  }

  return (
    <div className={`integration-root${isIndividualChat ? ' conversation-layout-mode' : ''}`}>
      <ThemeParticles />

      {!isIndividualChat && (
        <header className="integration-header">
          {/* Minimal Header: Raahi Logo on Left */}
          <NavLink className="integration-brand" to="/discover" aria-label="Raahi home">
            raahi<span>✦</span>
          </NavLink>

          {/* Minimal Header: 3-Line Hamburger Menu on Right */}
          <button
            type="button"
            className="integration-hamburger-btn"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation menu"
            aria-expanded={drawerOpen}
          >
            <span className="hamburger-line" aria-hidden="true" />
            <span className="hamburger-line" aria-hidden="true" />
            <span className="hamburger-line" aria-hidden="true" />
          </button>
        </header>
      )}

      {/* Hamburger Navigation Drawer Backdrop */}
      <div
        className={`integration-drawer-backdrop${drawerOpen ? ' visible' : ''}`}
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />

      {/* Slide-in Navigation Drawer */}
      <aside
        className={`integration-drawer${drawerOpen ? ' open' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label="Main navigation menu"
      >
        <div className="integration-drawer-header">
          <NavLink
            className="integration-brand"
            to="/discover"
            onClick={() => setDrawerOpen(false)}
            aria-label="Raahi home"
          >
            raahi<span>✦</span>
          </NavLink>
          <button
            type="button"
            className="integration-drawer-close"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close navigation menu"
          >
            ✕
          </button>
        </div>

        <nav className="integration-drawer-nav" aria-label="Application navigation">
          {/* 1. Main Navigation Group */}
          <div className="drawer-section">
            <span className="drawer-section-heading">Main Navigation</span>
            <NavLink
              to="/discover"
              className={({ isActive }) => `drawer-nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">🧭</span>
              <span className="drawer-nav-label">Discover</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </NavLink>

            <NavLink
              to="/matches"
              className={({ isActive }) => `drawer-nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">💖</span>
              <span className="drawer-nav-label">Matches</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </NavLink>

            <NavLink
              to="/conversations"
              className={({ isActive }) => `drawer-nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">💬</span>
              <span className="drawer-nav-label">Chat</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </NavLink>

            <NavLink
              to="/profile"
              className={({ isActive }) => `drawer-nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">👤</span>
              <span className="drawer-nav-label">Profiles</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </NavLink>
          </div>

          <hr className="drawer-divider" />

          {/* 2. Preferences & Support Group */}
          <div className="drawer-section">
            <span className="drawer-section-heading">Preferences & Support</span>
            <NavLink
              to="/settings"
              className={({ isActive }) => `drawer-nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">⚙️</span>
              <span className="drawer-nav-label">Settings</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </NavLink>

            <NavLink
              to="/privacy"
              className={({ isActive }) => `drawer-nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">🛡️</span>
              <span className="drawer-nav-label">Privacy & Safety</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </NavLink>

            <NavLink
              to="/help"
              className={({ isActive }) => `drawer-nav-item${isActive ? ' active' : ''}`}
              onClick={() => setDrawerOpen(false)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">🛟</span>
              <span className="drawer-nav-label">Help & Support</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </NavLink>
          </div>

          <hr className="drawer-divider" />

          {/* 3. Account Actions */}
          <div className="drawer-section drawer-account-section">
            <span className="drawer-section-heading">Account Actions</span>
            <button
              type="button"
              className="drawer-nav-item drawer-logout-item"
              onClick={() => setShowLogoutConfirm(true)}
            >
              <span className="drawer-nav-icon" aria-hidden="true">🚪</span>
              <span className="drawer-nav-label">Logout</span>
              <span className="drawer-nav-arrow" aria-hidden="true">›</span>
            </button>
          </div>
        </nav>
      </aside>

      {/* Logout Confirmation Dialog with Theme Support */}
      {showLogoutConfirm && (
        <div
          className="logout-modal-backdrop"
          onClick={() => setShowLogoutConfirm(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="logout-dialog-title"
        >
          <div
            className="logout-modal-card"
            onClick={e => e.stopPropagation()}
          >
            <div className="logout-modal-icon" aria-hidden="true">🚪</div>
            <h2 id="logout-dialog-title" className="logout-modal-title">Log Out of Raahi?</h2>
            <p className="logout-modal-desc">
              Are you sure you want to sign out? You will need to sign back in to access your matches and conversations.
            </p>
            <div className="logout-modal-actions">
              <button
                type="button"
                className="logout-btn-cancel"
                onClick={() => setShowLogoutConfirm(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="logout-btn-confirm"
                onClick={handleLogoutConfirm}
              >
                Log Out
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="integration-main">
        <Outlet />
      </main>
    </div>
  )
}

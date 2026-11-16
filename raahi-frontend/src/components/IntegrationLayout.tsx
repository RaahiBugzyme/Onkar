import { NavLink, Outlet, useLocation } from 'react-router'
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
  const isIndividualChat = location.pathname.startsWith('/conversations/') && location.pathname !== '/conversations'

  return (
    <div className={`integration-root${isIndividualChat ? ' conversation-layout-mode' : ''}`}>
      <ThemeParticles />
      {!isIndividualChat && (
        <header className="integration-header">
          <NavLink className="integration-brand" to="/" aria-label="Raahi home">
            raahi<span>✦</span>
          </NavLink>
          {/* Exactly 4 Primary Navigation Items */}
          <nav className="integration-nav" aria-label="Main navigation">
            <NavLink to="/discover" className={({ isActive }) => `integration-nav-link${isActive ? ' active' : ''}`}>
              Discover
            </NavLink>
            <NavLink to="/matches" className={({ isActive }) => `integration-nav-link${isActive ? ' active' : ''}`}>
              Matches
            </NavLink>
            <NavLink
              to="/conversations"
              aria-label="Chat conversations"
              className={({ isActive }) => `integration-nav-link integration-nav-link-chat${isActive ? ' active' : ''}`}
            >
              <span className="integration-chat-nav-icon" aria-hidden="true">✦</span> Chat
            </NavLink>
            <NavLink to="/profile" className={({ isActive }) => `integration-nav-link${isActive ? ' active' : ''}`}>
              Profile
            </NavLink>
          </nav>
        </header>
      )}

      <main className="integration-main">
        <Outlet />
      </main>

      {/* Floating Mobile Bottom Navigation Bar (4 Primary Destinations) */}
      {!isIndividualChat && (
        <nav className="app-mobile-nav-bar" aria-label="Mobile Navigation">
          <NavLink to="/discover" className={({ isActive }) => `mobile-nav-link${isActive ? ' active' : ''}`}>
            <span className="mobile-nav-icon" aria-hidden="true">🧭</span>
            <span>Discover</span>
          </NavLink>
          <NavLink to="/matches" className={({ isActive }) => `mobile-nav-link${isActive ? ' active' : ''}`}>
            <span className="mobile-nav-icon" aria-hidden="true">💖</span>
            <span>Matches</span>
          </NavLink>
          <NavLink to="/conversations" className={({ isActive }) => `mobile-nav-link${isActive ? ' active' : ''}`}>
            <span className="mobile-nav-icon" aria-hidden="true">💬</span>
            <span>Chat</span>
          </NavLink>
          <NavLink to="/profile" className={({ isActive }) => `mobile-nav-link${isActive ? ' active' : ''}`}>
            <span className="mobile-nav-icon" aria-hidden="true">👤</span>
            <span>Profile</span>
          </NavLink>
        </nav>
      )}
    </div>
  )
}

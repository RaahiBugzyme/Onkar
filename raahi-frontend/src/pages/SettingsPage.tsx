import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { resolveMediaUrl } from '../api/client'
import { useAuth } from '../state/AuthContext'
import { useDatingProfile } from '../state/DatingProfileContext'
import { updateDatingProfile } from '../api/datingProfile'
import { requestCurrentLocation } from '../utils/geolocation'
import { generationThemes, type GenerationId } from '../data/generations'
import { useTheme } from '../state/ThemeContext'
import { deleteMyAccount } from '../api/auth'
import { ApiError } from '../api/client'
import { fetchBlockedUsers, unblockUser as unblockUserApi, type BlockedUserItem } from '../api/safety'
import './settings.css'

function readStoredBool(key: string, defaultValue: boolean): boolean {
  try {
    const val = localStorage.getItem(key)
    if (val !== null) return val === 'true'
  } catch {}
  return defaultValue
}

function writeStoredBool(key: string, value: boolean) {
  try {
    localStorage.setItem(key, String(value))
  } catch {}
}

export function SettingsPage() {
  const { generation, setGeneration } = useTheme()
  const { user, updateUser, logout } = useAuth()
  const { profile, refreshProfile } = useDatingProfile()
  const navigate = useNavigate()

  const authoritativeName = user?.full_name || user?.username || 'Raahi member'
  const [displayName, setDisplayName] = useState(() => (user ? authoritativeName : 'Raahi member'))
  const [bio, setBio] = useState(() => user?.bio ?? '')
  const [photoError, setPhotoError] = useState(false)
  const [savingProfile, setSavingProfile] = useState(false)
  const [expandedProfile, setExpandedProfile] = useState(false)
  const [expandedAccountInfo, setExpandedAccountInfo] = useState(false)
  const [expandedLocation, setExpandedLocation] = useState(false)
  const [expandedBlocked, setExpandedBlocked] = useState(false)

  // Appearance
  const [darkMode, setDarkMode] = useState(() => readStoredBool('raahi_setting_darkMode', true))

  // AI & Privacy
  const [personalAiMemory, setPersonalAiMemory] = useState(() => user?.ai_memory_enabled ?? true)
  const [externalAiProcessing, setExternalAiProcessing] = useState(() => user?.ai_provider_processing_enabled ?? true)

  useEffect(() => {
    if (user) {
      setDisplayName(user.full_name || user.username || 'Raahi member')
      setBio(user.bio ?? '')
      setPersonalAiMemory(user.ai_memory_enabled ?? true)
      setExternalAiProcessing(user.ai_provider_processing_enabled ?? true)
    }
  }, [user])

  // Privacy & Safety
  const [notifications, setNotifications] = useState(() => readStoredBool('raahi_setting_notifications', true))
  const [matchCelebrations, setMatchCelebrations] = useState(() => readStoredBool('raahi_setting_matchCelebrations', true))
  const [readReceipts, setReadReceipts] = useState(() => readStoredBool('raahi_setting_readReceipts', true))
  const [ghostMode, setGhostMode] = useState(() => readStoredBool('raahi_setting_ghostMode', false))

  // Location
  const [cityInput, setCityInput] = useState(() => profile?.city || '')
  const [detectingLocation, setDetectingLocation] = useState(false)
  const [savingLocation, setSavingLocation] = useState(false)

  useEffect(() => {
    if (profile?.city) setCityInput(profile.city)
  }, [profile?.city])

  useEffect(() => {
    document.documentElement.setAttribute('data-color-scheme', darkMode ? 'dark' : 'light')
  }, [darkMode])

  // Blocked users
  const [blockedUsers, setBlockedUsers] = useState<BlockedUserItem[]>([])
  const [loadingBlocked, setLoadingBlocked] = useState(false)
  const [unblockingId, setUnblockingId] = useState<number | null>(null)

  const loadBlockedUsers = useCallback(async () => {
    if (!user) {
      setBlockedUsers([])
      return
    }
    setLoadingBlocked(true)
    try {
      const list = await fetchBlockedUsers()
      setBlockedUsers(list)
    } catch {
      setBlockedUsers([])
    } finally {
      setLoadingBlocked(false)
    }
  }, [user])

  useEffect(() => {
    void loadBlockedUsers()
  }, [loadBlockedUsers])

  // Feedback Toast
  const [toastMessage, setToastMessage] = useState<string | null>(null)

  function showToast(msg: string) {
    setToastMessage(msg)
    window.setTimeout(() => setToastMessage(null), 3000)
  }

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault()
    const nextName = displayName.trim()
    const nextBio = bio.trim()
    if (nextName.length < 2) {
      showToast('Please enter a display name with at least 2 characters.')
      return
    }
    setSavingProfile(true)
    try {
      if (user) {
        await updateUser({
          full_name: nextName,
          bio: nextBio,
        })
        void refreshProfile().catch(() => undefined)
      }
      showToast('Profile saved successfully! ✨')
      setExpandedProfile(false)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save changes. Please try again.'
      showToast(message)
    } finally {
      setSavingProfile(false)
    }
  }

  async function handleSaveLocation(nextCity?: string) {
    const targetCity = (nextCity ?? cityInput).trim()
    if (targetCity.length < 2) {
      showToast('Please enter a valid city name (at least 2 characters).')
      return
    }
    setSavingLocation(true)
    try {
      if (user) {
        await updateDatingProfile({ city: targetCity })
        await refreshProfile()
      }
      setCityInput(targetCity)
      showToast(`Location updated to ${targetCity} 📍`)
      setExpandedLocation(false)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Could not save location.')
    } finally {
      setSavingLocation(false)
    }
  }

  async function handleDetectLocation() {
    setDetectingLocation(true)
    const res = await requestCurrentLocation()
    setDetectingLocation(false)
    if (res.city) {
      setCityInput(res.city)
      await handleSaveLocation(res.city)
    } else if (res.error) {
      showToast(res.error)
    }
  }

  async function toggleAiConsent(field: 'ai_provider_processing_enabled' | 'ai_memory_enabled', value: boolean) {
    if (field === 'ai_memory_enabled') setPersonalAiMemory(value)
    else setExternalAiProcessing(value)

    if (user) {
      try {
        await updateUser({ [field]: value })
        showToast('Preference saved to account.')
      } catch {
        showToast('Failed to save to server, saved locally.')
      }
    } else {
      showToast('Saved to local preferences.')
    }
  }

  async function handleUnblock(item: BlockedUserItem) {
    setUnblockingId(item.user_id)
    try {
      if (user) {
        await unblockUserApi(item.user_id)
        window.dispatchEvent(new CustomEvent('raahi:user-unblocked', { detail: { userId: item.user_id } }))
      }
      await loadBlockedUsers()
      showToast(`Unblocked @${item.username}`)
    } catch (cause) {
      showToast(cause instanceof Error ? cause.message : 'Could not unblock user.')
    } finally {
      setUnblockingId(null)
    }
  }

  // Account deletion state
  const [deletingAccount, setDeletingAccount] = useState(false)

  function handleLogout() {
    logout()
    showToast('Logged out of session.')
    navigate('/login')
  }

  async function handleDeleteAccount() {
    if (deletingAccount) return
    if (!window.confirm('Are you sure you want to permanently delete your account, profile, photos, matches, and messages? This action cannot be undone.')) return
    setDeletingAccount(true)
    try {
      await deleteMyAccount()
      logout()
      showToast('Your account and all data have been permanently deleted.')
      navigate('/')
    } catch (reason) {
      showToast(reason instanceof ApiError ? reason.message : 'Could not delete account right now. Please try again.')
    } finally {
      setDeletingAccount(false)
    }
  }

  const theme = generationThemes[generation] || generationThemes.genz
  const currentDisplayName = user?.full_name || user?.username || displayName || 'Raahi member'
  const userInitial = (currentDisplayName.trim()[0] || 'R').toUpperCase()

  const isFaceVerified = Boolean(profile?.is_face_verified)
  const isIdVerified = Boolean(profile?.is_id_verified)
  const isFullyVerified = Boolean((isFaceVerified && isIdVerified) || profile?.verification_status === 'verified')
  const isPendingVerification = profile?.verification_status === 'pending'
  const isFailedVerification = profile?.verification_status === 'rejected'

  const primaryPhoto = profile?.photos?.find(p => p.is_primary)?.photo_url || profile?.photos?.[0]?.photo_url || null

  return (
    <section className="settings-screen page-enter" aria-label="Application Settings">
      {toastMessage && (
        <div className="discover-feedback-toast" role="status">
          {toastMessage}
        </div>
      )}

      {/* Back Link to Profile */}
      <Link to="/profile" className="settings-back-link">
        <span className="e e-swing" aria-hidden="true">←</span> Back to Profile
      </Link>

      {/* Page Header */}
      <header className="settings-page-header fiu">
        <div>
          <p className="integration-eyebrow">PREFERENCES & SAFETY</p>
          <h1 className="settings-page-title">Settings</h1>
          <p className="settings-page-subtitle">Configure your vibe, conversation AI, and privacy controls</p>
        </div>
        <span className="settings-mode-pill">
          {theme.name.toUpperCase()}
        </span>
      </header>

      {/* Top User Hero Card */}
      <div className="settings-user-hero">
        <div className="settings-user-hero-left">
          <div
            className="settings-avatar-circle"
            style={{ borderColor: theme.primary, boxShadow: `0 0 18px ${theme.glow}`, overflow: 'hidden' }}
          >
            {primaryPhoto && !photoError ? (
              <img
                src={resolveMediaUrl(primaryPhoto)}
                alt={currentDisplayName}
                className="settings-avatar-img"
                onError={() => setPhotoError(true)}
              />
            ) : (
              <span>{userInitial}</span>
            )}
          </div>
          <div>
            <h2 className="settings-user-name">
              {currentDisplayName}
              {isFullyVerified && (
                <span style={{ marginLeft: 8, color: '#4ade80', fontSize: '0.8rem', fontWeight: 800 }}>
                  🛡️ VERIFIED
                </span>
              )}
            </h2>
            <p className="settings-user-sub">
              {user?.username ? `@${user.username}` : '@member'} · {theme.name} Vibe
            </p>
          </div>
        </div>
        <Link to="/profile/edit" className="settings-edit-pill" aria-label="Edit Full Profile">
          ✏️ Edit Profile
        </Link>
      </div>

      {/* 1. SECTION: ACCOUNT */}
      <div className="settings-group">
        <h3 className="settings-group-title">Account</h3>
        <div className="settings-group-card">
          <div
            className="settings-row clickable"
            onClick={() => setExpandedProfile(prev => !prev)}
            role="button"
            tabIndex={0}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setExpandedProfile(prev => !prev) }}
            aria-expanded={expandedProfile}
          >
            <div className="settings-row-icon" aria-hidden="true">👤</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Display Name & Bio</span>
              <span className="settings-row-desc">Quick editor for your name and mini-bio</span>
            </div>
            <div className="settings-row-ctrl">
              <span className={`settings-chevron${expandedProfile ? ' expanded' : ''}`} aria-hidden="true">›</span>
            </div>
          </div>

          {expandedProfile && (
            <form onSubmit={handleSaveProfile} className="settings-row-expandable">
              <label className="settings-mini-field">
                <span>Display Name</span>
                <input
                  type="text"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  maxLength={30}
                  placeholder="Your display name"
                />
              </label>
              <label className="settings-mini-field">
                <span>Bio</span>
                <textarea
                  value={bio}
                  onChange={e => setBio(e.target.value)}
                  maxLength={200}
                  rows={2}
                  placeholder="Write a short bio.."
                />
              </label>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                <button
                  type="button"
                  className="settings-mini-btn-secondary"
                  onClick={() => {
                    setDisplayName(user?.full_name || user?.username || 'Raahi member')
                    setBio(user?.bio ?? '')
                    setExpandedProfile(false)
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="settings-mini-btn-primary"
                  disabled={savingProfile}
                >
                  {savingProfile ? 'Saving…' : 'Save Changes'}
                </button>
              </div>
            </form>
          )}

          <div
            className="settings-row clickable"
            onClick={() => setExpandedAccountInfo(prev => !prev)}
            role="button"
            tabIndex={0}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setExpandedAccountInfo(prev => !prev) }}
            aria-expanded={expandedAccountInfo}
          >
            <div className="settings-row-icon" aria-hidden="true">ℹ️</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Account Information</span>
              <span className="settings-row-desc">Username, email, and membership details</span>
            </div>
            <div className="settings-row-ctrl">
              <span className={`settings-chevron${expandedAccountInfo ? ' expanded' : ''}`} aria-hidden="true">›</span>
            </div>
          </div>

          {expandedAccountInfo && (
            <div className="settings-row-expandable" style={{ fontSize: '0.84rem' }}>
              <div style={{ display: 'grid', gap: 10, padding: '4px 0' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6 }}>
                  <span style={{ color: 'rgba(255,255,255,0.6)' }}>Username</span>
                  <span style={{ fontWeight: 700 }}>@{user?.username || 'member'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6 }}>
                  <span style={{ color: 'rgba(255,255,255,0.6)' }}>Email Address</span>
                  <span>{user?.email || 'Registered account'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6 }}>
                  <span style={{ color: 'rgba(255,255,255,0.6)' }}>Member Since</span>
                  <span>{profile?.created_at ? new Date(profile.created_at).toLocaleDateString() : 'Active Member'}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'rgba(255,255,255,0.6)' }}>Verification Status</span>
                  <span style={{ color: isFullyVerified ? '#4ade80' : isPendingVerification ? '#fbbf24' : 'rgba(255,255,255,0.5)', fontWeight: 700 }}>
                    {isFullyVerified ? '🛡️ Verified' : isPendingVerification ? '⏳ Pending' : 'Unverified'}
                  </span>
                </div>
              </div>
            </div>
          )}

          <Link to="/profile/edit" className="settings-row clickable">
            <div className="settings-row-icon" aria-hidden="true">🎨</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Full Profile & Photos</span>
              <span className="settings-row-desc">Manage portraits, prompts, and interest chips</span>
            </div>
            <div className="settings-row-ctrl">
              <span className="settings-chevron" aria-hidden="true">›</span>
            </div>
          </Link>
        </div>
      </div>

      {/* 2. SECTION: PRIVACY & SAFETY */}
      <div className="settings-group">
        <h3 className="settings-group-title">Privacy & Safety</h3>
        <div className="settings-group-card">
          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">👻</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Ghost Mode</span>
              <span className="settings-row-desc">Hide online and last seen activity from matches</span>
            </div>
            <div className="settings-row-ctrl">
              <label className="settings-switch" aria-label="Toggle Ghost Mode">
                <input
                  type="checkbox"
                  checked={ghostMode}
                  onChange={e => {
                    const checked = e.target.checked
                    setGhostMode(checked)
                    writeStoredBool('raahi_setting_ghostMode', checked)
                    showToast(checked ? 'Ghost mode active 👻' : 'Ghost mode disabled')
                  }}
                />
                <span className="settings-switch-slider" />
              </label>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">✓✓</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Read Receipts</span>
              <span className="settings-row-desc">Show checkmarks when messages are seen</span>
            </div>
            <div className="settings-row-ctrl">
              <label className="settings-switch" aria-label="Toggle Read Receipts">
                <input
                  type="checkbox"
                  checked={readReceipts}
                  onChange={e => {
                    const checked = e.target.checked
                    setReadReceipts(checked)
                    writeStoredBool('raahi_setting_readReceipts', checked)
                    showToast(checked ? 'Read receipts enabled ✓✓' : 'Read receipts disabled')
                  }}
                />
                <span className="settings-switch-slider" />
              </label>
            </div>
          </div>

          <div
            className="settings-row clickable"
            onClick={() => setExpandedLocation(prev => !prev)}
            role="button"
            tabIndex={0}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setExpandedLocation(prev => !prev) }}
            aria-expanded={expandedLocation}
          >
            <div className="settings-row-icon" aria-hidden="true">📍</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Discovery Location</span>
              <span className="settings-row-desc">
                Current city: <strong>{cityInput || profile?.city || 'Not set'}</strong>
              </span>
            </div>
            <div className="settings-row-ctrl">
              <span className={`settings-chevron${expandedLocation ? ' expanded' : ''}`} aria-hidden="true">›</span>
            </div>
          </div>

          {expandedLocation && (
            <div className="settings-row-expandable">
              <p style={{ margin: '0 0 10px', fontSize: '.76rem', color: 'rgba(255,255,255,.6)' }}>
                Used to show matches nearby. Your exact GPS coordinates are never stored or shared with other members.
              </p>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  className="settings-mini-btn-secondary"
                  onClick={handleDetectLocation}
                  disabled={detectingLocation}
                  style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  {detectingLocation ? 'Detecting…' : '📍 Detect Current Location'}
                </button>
              </div>
              <form
                onSubmit={e => {
                  e.preventDefault()
                  void handleSaveLocation()
                }}
                style={{ display: 'flex', gap: 8 }}
              >
                <input
                  type="text"
                  value={cityInput}
                  onChange={e => setCityInput(e.target.value)}
                  placeholder="Enter your city (e.g. Mumbai)"
                  maxLength={60}
                  style={{ flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(0,0,0,0.3)', color: '#fff' }}
                />
                <button
                  type="submit"
                  className="settings-mini-btn-primary"
                  disabled={savingLocation}
                >
                  {savingLocation ? 'Saving…' : 'Save'}
                </button>
              </form>
            </div>
          )}
        </div>
      </div>

      {/* 3. SECTION: NOTIFICATIONS */}
      <div className="settings-group">
        <h3 className="settings-group-title">Notifications</h3>
        <div className="settings-group-card">
          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">🔔</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Message Alerts</span>
              <span className="settings-row-desc">In-app notifications for incoming conversation chats</span>
            </div>
            <div className="settings-row-ctrl">
              <label className="settings-switch" aria-label="Toggle Message Alerts">
                <input
                  type="checkbox"
                  checked={notifications}
                  onChange={e => {
                    const checked = e.target.checked
                    setNotifications(checked)
                    writeStoredBool('raahi_setting_notifications', checked)
                    showToast(checked ? 'Message alerts enabled 🔔' : 'Message alerts muted 🔕')
                  }}
                />
                <span className="settings-switch-slider" />
              </label>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">🎉</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Match Celebrations</span>
              <span className="settings-row-desc">Display celebration popups on mutual sparks</span>
            </div>
            <div className="settings-row-ctrl">
              <label className="settings-switch" aria-label="Toggle Match Celebrations">
                <input
                  type="checkbox"
                  checked={matchCelebrations}
                  onChange={e => {
                    const checked = e.target.checked
                    setMatchCelebrations(checked)
                    writeStoredBool('raahi_setting_matchCelebrations', checked)
                    showToast(checked ? 'Match celebrations enabled 🎉' : 'Celebrations muted')
                  }}
                />
                <span className="settings-switch-slider" />
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* 4. SECTION: APPEARANCE */}
      <div className="settings-group">
        <h3 className="settings-group-title">Appearance</h3>
        <div className="settings-group-card">
          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">🌙</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Dark Mode</span>
              <span className="settings-row-desc">
                {darkMode ? 'Purple night is active · tap for light' : 'Light cosmic mode enabled'}
              </span>
            </div>
            <div className="settings-row-ctrl">
              <label className="settings-switch" aria-label="Toggle Dark Mode">
                <input
                  type="checkbox"
                  checked={darkMode}
                  onChange={e => {
                    const checked = e.target.checked
                    setDarkMode(checked)
                    writeStoredBool('raahi_setting_darkMode', checked)
                    showToast(checked ? 'Purple night mode active 🌙' : 'Light cosmic mode enabled ☀️')
                  }}
                />
                <span className="settings-switch-slider" />
              </label>
            </div>
          </div>

          <div className="settings-theme-section">
            <div className="settings-row">
              <div className="settings-row-icon" aria-hidden="true">{theme.emoji}</div>
              <div className="settings-row-info">
                <span className="settings-row-title">Active Era Theme</span>
                <span className="settings-row-desc">{theme.name} palette · {theme.eraDescription.split('·')[0].trim()}</span>
              </div>
              <div className="settings-row-ctrl">
                <span className="settings-status-pill" style={{ color: theme.primary, borderColor: theme.cardBorder }}>
                  {theme.name}
                </span>
              </div>
            </div>

            <div className="settings-theme-grid" role="radiogroup" aria-label="Choose application theme">
              {(Object.keys(generationThemes) as GenerationId[]).map(themeId => {
                const item = generationThemes[themeId]
                const isSelected = generation === themeId
                return (
                  <button
                    key={themeId}
                    type="button"
                    role="radio"
                    aria-checked={isSelected}
                    className={`settings-theme-option${isSelected ? ' selected' : ''}`}
                    onClick={() => {
                      setGeneration(themeId)
                      showToast(`Switched to ${item.name} theme ✨`)
                    }}
                    style={{
                      '--opt-primary': item.primary,
                      '--opt-secondary': item.secondary,
                      '--opt-glow': item.glow,
                      '--opt-bg': item.background,
                      '--opt-border': item.cardBorder,
                    } as React.CSSProperties}
                  >
                    <div className="theme-option-top">
                      <span className="theme-option-emoji">{item.emoji}</span>
                      <span className="theme-option-radio" aria-hidden="true">
                        {isSelected && <span className="theme-option-radio-dot" />}
                      </span>
                    </div>
                    <strong className="theme-option-name">{item.name}</strong>
                    <div className="theme-option-swatches" aria-hidden="true">
                      <span className="theme-swatch" style={{ background: item.primary }} />
                      <span className="theme-swatch" style={{ background: item.secondary }} />
                      <span className="theme-swatch" style={{ background: item.background }} />
                    </div>
                    <small className="theme-option-tags">{item.eraTags.slice(0, 2).join(' · ')}</small>
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* 5. SECTION: CONVERSATION AI */}
      <div className="settings-group">
        <h3 className="settings-group-title">Conversation AI</h3>
        <div className="settings-group-card">
          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">✦</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Personal AI Memory</span>
              <span className="settings-row-desc">Let AI remember useful chat context for tailored suggestions</span>
            </div>
            <div className="settings-row-ctrl">
              <label className="settings-switch" aria-label="Toggle Personal AI Memory">
                <input
                  type="checkbox"
                  checked={personalAiMemory}
                  onChange={e => void toggleAiConsent('ai_memory_enabled', e.target.checked)}
                />
                <span className="settings-switch-slider" />
              </label>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">🤖</div>
            <div className="settings-row-info">
              <span className="settings-row-title">AI Suggestion Coach</span>
              <span className="settings-row-desc">Enable external AI processing for icebreakers and advice</span>
            </div>
            <div className="settings-row-ctrl">
              <label className="settings-switch" aria-label="Toggle AI Suggestions Coach">
                <input
                  type="checkbox"
                  checked={externalAiProcessing}
                  onChange={e => void toggleAiConsent('ai_provider_processing_enabled', e.target.checked)}
                />
                <span className="settings-switch-slider" />
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* 6. SECTION: VERIFICATION */}
      <div className="settings-group">
        <h3 className="settings-group-title">Verification</h3>
        <div className="settings-group-card">
          <Link to="/verification" className="settings-row clickable">
            <div className="settings-row-icon" aria-hidden="true">🪪</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Identity & Photo Verification</span>
              <span className="settings-row-desc">Submit selfie & student/work ID for verified badge</span>
            </div>
            <div className="settings-row-ctrl">
              {isFullyVerified ? (
                <span className="settings-status-pill" style={{ color: '#4ade80', borderColor: 'rgba(74,222,128,0.3)', background: 'rgba(74,222,128,0.1)' }}>
                  Verified 🛡️
                </span>
              ) : isPendingVerification ? (
                <span className="settings-status-pill" style={{ color: '#fbbf24', borderColor: 'rgba(251,191,36,0.3)', background: 'rgba(251,191,36,0.1)' }}>
                  Pending Review ⏳
                </span>
              ) : isFailedVerification ? (
                <span className="settings-status-pill" style={{ color: '#f87171', borderColor: 'rgba(248,113,113,0.3)', background: 'rgba(248,113,113,0.1)' }}>
                  Action Needed ⚠️
                </span>
              ) : (
                <span className="settings-status-pill" style={{ color: 'rgba(255,255,255,0.6)', borderColor: 'rgba(255,255,255,0.2)' }}>
                  Not Verified
                </span>
              )}
              <span className="settings-chevron" aria-hidden="true">›</span>
            </div>
          </Link>
        </div>
      </div>

      {/* 7. SECTION: BLOCKED USERS */}
      <div className="settings-group">
        <h3 className="settings-group-title">Blocked Users</h3>
        <div className="settings-group-card">
          <div
            className="settings-row clickable"
            onClick={() => setExpandedBlocked(prev => !prev)}
            role="button"
            tabIndex={0}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setExpandedBlocked(prev => !prev) }}
            aria-expanded={expandedBlocked}
          >
            <div className="settings-row-icon" aria-hidden="true">🚫</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Restricted Profiles</span>
              <span className="settings-row-desc">
                {loadingBlocked ? 'Loading blocked list…' : blockedUsers.length ? `${blockedUsers.length} blocked user${blockedUsers.length > 1 ? 's' : ''}` : 'No blocked users'}
              </span>
            </div>
            <div className="settings-row-ctrl">
              <span className={`settings-chevron${expandedBlocked ? ' expanded' : ''}`} aria-hidden="true">›</span>
            </div>
          </div>

          {expandedBlocked && (
            <div className="settings-row-expandable">
              <p style={{ margin: '0 0 10px', fontSize: '.74rem', color: 'rgba(255,255,255,.5)' }}>
                Blocked people cannot message you or see your profile in Discover.
              </p>
              {loadingBlocked ? (
                <p style={{ margin: '8px 0', fontSize: '.78rem', color: 'rgba(255,255,255,.6)' }}>Loading…</p>
              ) : blockedUsers.length ? (
                <div style={{ display: 'grid', gap: 8 }}>
                  {blockedUsers.map(item => {
                    const name = item.full_name || item.username
                    const initial = (name.trim()[0] || 'R').toUpperCase()
                    return (
                      <div key={item.id || item.user_id} className="settings-blocked-item">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                          {item.photo_url ? (
                            <img
                              src={resolveMediaUrl(item.photo_url)}
                              alt={name}
                              style={{ width: 34, height: 34, borderRadius: '50%', objectFit: 'cover', border: '1px solid rgba(255,255,255,0.15)', flexShrink: 0 }}
                              onError={(e) => {
                                e.currentTarget.style.display = 'none'
                              }}
                            />
                          ) : (
                            <div style={{ width: 34, height: 34, borderRadius: '50%', background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', display: 'grid', placeItems: 'center', fontSize: '0.85rem', fontWeight: 800, color: 'var(--es)', flexShrink: 0 }}>
                              {initial}
                            </div>
                          )}
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontWeight: 700, fontSize: '0.86rem', color: '#ffffff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
                            <div style={{ fontSize: '0.72rem', color: 'rgba(255,255,255,0.5)' }}>@{item.username}</div>
                          </div>
                        </div>
                        <button
                          type="button"
                          className="settings-unblock-btn"
                          onClick={() => void handleUnblock(item)}
                          disabled={unblockingId === item.user_id}
                        >
                          {unblockingId === item.user_id ? 'Unblocking…' : 'Unblock'}
                        </button>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p style={{ margin: 0, fontSize: '.76rem', color: 'rgba(255,255,255,.4)' }}>
                  No blocked profiles.
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 8. SECTION: ACCOUNT MANAGEMENT */}
      <div className="settings-group">
        <h3 className="settings-group-title">Account Management</h3>
        <div className="settings-group-card">
          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">🚪</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Sign Out</span>
              <span className="settings-row-desc">Log out of your current session on this device</span>
            </div>
            <div className="settings-row-ctrl">
              <button
                type="button"
                className="settings-ctrl-btn warning"
                onClick={handleLogout}
              >
                Sign Out
              </button>
            </div>
          </div>

          <div className="settings-row">
            <div className="settings-row-icon" aria-hidden="true">🗑️</div>
            <div className="settings-row-info">
              <span className="settings-row-title">Delete Account Data</span>
              <span className="settings-row-desc">Permanently delete your account, profile, photos, and messages</span>
            </div>
            <div className="settings-row-ctrl">
              <button
                type="button"
                className="settings-ctrl-btn danger"
                disabled={deletingAccount}
                onClick={() => void handleDeleteAccount()}
              >
                {deletingAccount ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

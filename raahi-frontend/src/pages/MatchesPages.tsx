import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { AccountAccess } from '../components/AccountAccess'
import { Card } from '../components/Card'
import { LoadingState } from '../components/LoadingState'
import { PageContainer } from '../components/PageContainer'
import { ApiError, fetchProtectedBlob, getAuthToken, resolveMediaUrl } from '../api/client'
import { mergeChatMessage, reduceChatMessages } from '../api/chatState'
import { BlockConfirmationModal, ReportUserModal, SafetyMenuDropdown } from '../components/SafetyModals'
import {
  chatSocketUrl, deleteConversation, deleteMessage, fetchChats, fetchCoach, fetchInsights,
  fetchMatch, fetchMatches, fetchMessages, fetchSuggestions, sendTextMessage,
  trackSuggestionEvent, uploadAttachment, uploadVoice,
  type ChatMessage, type ChatSummary, type IncomingMessageEvent, type MatchDetail, type MatchItem,
} from '../api/chat'
import { useAuth, type CurrentUser } from '../state/AuthContext'
import { useDatingProfile } from '../state/DatingProfileContext'
import type { ProfilePhoto } from '../api/datingProfile'
import { useTheme } from '../state/ThemeContext'
import '../styles/matches.css'

function apiErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Your session expired. Sign in again to continue.'
    if (error.status === 403) return error.message || 'This action is not available for this conversation.'
    if (error.status === 404 || error.status === 410) return 'This match or conversation is no longer available.'
    if (error.status === 429 || error.status === 503) return 'Raahi is busy right now. Please wait a moment and try again.'
    return error.message || fallback
  }
  return fallback
}

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map(part => part[0]?.toUpperCase() ?? '').join('') || 'R'
}

export function getPrimaryPhotoUrl(photos?: ProfilePhoto[] | null): string | null {
  if (!photos || photos.length === 0) return null
  const primary = photos.find(p => p.is_primary)
  return (primary ?? photos[0])?.photo_url || null
}

function Avatar({ name, photo, small = false }: { name: string; photo?: string | null; small?: boolean }) {
  const [imgError, setImgError] = useState(false)
  useEffect(() => {
    setImgError(false)
  }, [photo])

  if (photo && !imgError) {
    return (
      <img
        src={resolveMediaUrl(photo)}
        alt={name}
        className={`matches-avatar${small ? ' small' : ''}`}
        style={{ objectFit: 'cover' }}
        onError={() => setImgError(true)}
      />
    )
  }
  return <span className={`matches-avatar${small ? ' small' : ''}`} aria-hidden="true">{initials(name)}</span>
}

function MatchAvatarImage({
  photo,
  name,
  fallbackInitial,
  className,
}: {
  photo?: string | null
  name: string
  fallbackInitial: string
  className: string
}) {
  const [imgError, setImgError] = useState(false)
  useEffect(() => {
    setImgError(false)
  }, [photo])

  if (photo && !imgError) {
    return (
      <img
        src={resolveMediaUrl(photo)}
        alt={name}
        className={className}
        onError={() => setImgError(true)}
      />
    )
  }
  return (
    <span className={className.includes('conv-row') ? 'conv-row-initial' : 'new-match-initial'}>
      {fallbackInitial}
    </span>
  )
}

function MatchCelebrationModal({
  match,
  user,
  userPrimaryPhoto,
  onClose,
}: {
  match: { name: string; initials: string; ringColor: string; chatId: number; photo?: string }
  user: CurrentUser | null
  userPrimaryPhoto: string | null
  onClose: () => void
}) {
  const [userPhotoFailed, setUserPhotoFailed] = useState(false)
  const [matchPhotoFailed, setMatchPhotoFailed] = useState(false)

  useEffect(() => {
    setUserPhotoFailed(false)
  }, [userPrimaryPhoto])

  useEffect(() => {
    setMatchPhotoFailed(false)
  }, [match.photo])

  const userInitial = user?.username ? user.username[0]?.toUpperCase() : '😎'

  return (
    <div className="discover-celebration-overlay" role="dialog" aria-modal="true" aria-label="Match celebration">
      <div className="celebration-modal-card">
        <p className="celebration-eyebrow">MUTUAL CONNECTION</p>
        <h2 className="celebration-title">It’s a Match! 🎉</h2>
        <p className="celebration-subtitle">
          You and {match.name} connected on Raahi. Say hi and start the conversation!
        </p>
        <div className="celebration-clash" aria-hidden="true">
          <div
            className="celebration-avatar-ring"
            style={{ borderColor: 'var(--ep)', boxShadow: '0 0 24px rgba(216,61,180,0.5)', overflow: 'hidden' }}
          >
            {userPrimaryPhoto && !userPhotoFailed ? (
              <img
                src={resolveMediaUrl(userPrimaryPhoto)}
                alt={user?.full_name || user?.username || 'You'}
                className="celebration-avatar-img"
                onError={() => setUserPhotoFailed(true)}
              />
            ) : (
              <span>{userInitial}</span>
            )}
          </div>
          <span className="celebration-sparkle-center">💗</span>
          <div
            className="celebration-avatar-ring"
            style={{ borderColor: match.ringColor, boxShadow: `0 0 24px ${match.ringColor}`, overflow: 'hidden' }}
          >
            {match.photo && !matchPhotoFailed ? (
              <img
                src={resolveMediaUrl(match.photo)}
                alt={match.name}
                className="celebration-avatar-img"
                onError={() => setMatchPhotoFailed(true)}
              />
            ) : (
              <span>{match.initials}</span>
            )}
          </div>
        </div>
        <div className="celebration-actions">
          <Link
            to={`/conversations/${match.chatId}`}
            className="celebration-chat-btn bpulse"
            onClick={onClose}
          >
            Send Message 👋
          </Link>
          <button
            type="button"
            className="celebration-keep-btn"
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function AuthGate({ message = 'Sign in to see your real matches and conversations.' }: { message?: string }) {
  return <PageContainer className="matches-page"><Card className="matches-empty-card matches-auth-card">
    <span className="matches-empty-icon" aria-hidden="true">✦</span>
    <p className="integration-eyebrow">YOUR RAAHI ACCOUNT</p><h1>Connect to your people</h1><p>{message}</p>
    <AccountAccess />
  </Card></PageContainer>
}

function PageError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <Card className="matches-empty-card matches-error-card"><span className="matches-empty-icon" aria-hidden="true">☄</span><h2>We couldn’t load this right now</h2><p role="alert">{message}</p>{onRetry && <button type="button" className="matches-outline-button" onClick={onRetry}>Try again</button>}</Card>
}

export function MatchesPage() {
  const { user, loading: authLoading } = useAuth()
  const { profile } = useDatingProfile()
  const { generation } = useTheme()
  const [matches, setMatches] = useState<MatchItem[]>([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [celebratingMatch, setCelebratingMatch] = useState<{ name: string; initials: string; ringColor: string; chatId: number; photo?: string } | null>(null)

  const userPrimaryPhoto = useMemo(() => getPrimaryPhotoUrl(profile?.photos), [profile?.photos])

  const load = useCallback(async () => {
    if (!user) return
    setLoading(true); setError('')
    try {
      const result = await fetchMatches(0, 50)
      setMatches(result.matches)
      setHasMore(result.has_more)
    }
    catch (reason) { setError(apiErrorMessage(reason, 'Your matches could not be loaded.')) }
    finally { setLoading(false) }
  }, [user])

  async function loadMore() {
    if (loadingMore || !hasMore) return
    setLoadingMore(true)
    try {
      const result = await fetchMatches(matches.length, 50)
      setMatches(current => [...current, ...result.matches])
      setHasMore(result.has_more)
    } catch (reason) { setError(apiErrorMessage(reason, 'More matches could not be loaded.')) }
    finally { setLoadingMore(false) }
  }

  useEffect(() => { if (user) void load(); else setLoading(false) }, [load, user])
  useEffect(() => {
    const handleReload = () => { if (user) void load() }
    window.addEventListener('raahi:user-blocked', handleReload)
    window.addEventListener('raahi:match-ended', handleReload)
    return () => {
      window.removeEventListener('raahi:user-blocked', handleReload)
      window.removeEventListener('raahi:match-ended', handleReload)
    }
  }, [load, user])

  const filteredReal = useMemo(() => matches.filter(match => `${match.matched_user.full_name ?? ''} ${match.matched_user.username ?? ''} ${match.city ?? ''}`.toLowerCase().includes(search.trim().toLowerCase())), [matches, search])

  const eraModeLabel = generation === 'millennial' ? 'Millennial' : generation === 'zillenial' ? 'Zillenial' : 'Gen Z'
  const eraModeIcon = generation === 'millennial' ? '⚡' : generation === 'zillenial' ? '🎭' : '💀'

  if (authLoading) return <LoadingState label="Checking your Raahi session…" />

  if (!user) {
    return <Navigate to="/login" replace />
  }
  const displayCount = filteredReal.length

  return (
    <PageContainer className="matches-page page-enter">
      <div className="matches-shell">
        {/* Top Header */}
        <header className="matches-topbar">
          <div className="matches-topbar-left">
            <span className="matches-count-badge" aria-label="Matches count">{displayCount}</span>
            <div className="matches-title-wrap">
              <h1 className="matches-title">{eraModeIcon} Matches</h1>
              <p className="matches-subtitle">
                <span className="matches-live-dot" /> {displayCount} active · {eraModeLabel}
              </p>
            </div>
          </div>
          <button type="button" className="matches-bell-btn" aria-label="Notifications">
            <span className="matches-bell-icon" aria-hidden="true">🔔</span>
          </button>
        </header>

        {/* Search Input */}
        <div className="matches-search-wrap">
          <span className="matches-search-glass" aria-hidden="true">🔍</span>
          <input
            type="text"
            className="matches-search-input"
            value={search}
            onChange={event => setSearch(event.currentTarget.value)}
            placeholder="Search matches by name, vibe or city..."
            aria-label="Search matches"
          />
        </div>

        {/* Scrollable Matches Content Container */}
        <div className="matches-scroll-content">
          {/* NEW MATCHES Section */}
          {matches.length > 0 && (
            <section className="matches-section" aria-label="New matches">
              <h2 className="matches-section-heading">✨ NEW MATCHES</h2>
              <div className="new-matches-scroll">
                {matches.slice(0, 10).map(match => {
                  const name = match.matched_user.full_name || match.matched_user.username || 'Match'
                  const photo = match.photos?.[0] || match.matched_user.photo_url || match.matched_user.photos?.[0]
                  return (
                    <Link
                      key={match.id}
                      to={`/conversations/${match.chat_id}`}
                      className="new-match-avatar-card"
                      title={`Chat with ${name}`}
                    >
                      <span className="new-match-pill">NEW</span>
                      <div className="new-match-ring" style={{ borderColor: 'var(--ep)', boxShadow: '0 0 14px rgba(216, 61, 180, 0.35)' }}>
                        <MatchAvatarImage
                          photo={photo}
                          name={name}
                          fallbackInitial={initials(name)}
                          className="new-match-avatar-img"
                        />
                        <span className="new-match-corner" aria-hidden="true">💖</span>
                      </div>
                      <span className="new-match-name">{name}</span>
                      <span className="new-match-status">{match.city || 'Active'}</span>
                    </Link>
                  )
                })}
              </div>
            </section>
          )}

          {/* MUTUAL CONNECTIONS Section */}
          <section className="matches-section" aria-label="Mutual connections">
            <h2 className="matches-section-heading">💖 MUTUAL CONNECTIONS</h2>
            {error ? (
              <PageError message={error} onRetry={() => void load()} />
            ) : loading ? (
              <LoadingState label="Loading your matches…" />
            ) : filteredReal.length ? (
              <div className="conversations-cards-column">
                {filteredReal.map(match => (
                  <MatchCard key={match.id} match={match} />
                ))}
                {hasMore && !search.trim() && (
                  <button
                    className="matches-outline-button matches-load-more"
                    type="button"
                    disabled={loadingMore}
                    onClick={() => void loadMore()}
                  >
                    {loadingMore ? 'Loading…' : 'Load more matches'}
                  </button>
                )}
              </div>
            ) : (
              <Card className="matches-empty-card" style={{ margin: '12px 0' }}>
                <span className="matches-empty-icon" aria-hidden="true">☾</span>
                <p className="integration-eyebrow">{search.trim() ? 'NO SEARCH RESULTS' : 'A LITTLE QUIET HERE'}</p>
                <h3 style={{ margin: '6px 0', fontSize: '1.1rem' }}>
                  {search.trim() ? `No matches found for “${search}”` : 'Your next connection will show up here'}
                </h3>
                <p style={{ fontSize: '.84rem' }}>
                  {search.trim() ? 'Try searching another name, city, or vibe.' : 'New mutual matches will appear here when you like each other in Discover.'}
                </p>
                <div className="matches-card-actions" style={{ justifyContent: 'center', marginTop: 12 }}>
                  <Link className="matches-primary-button" to="/discover">
                    Start Discovering 🧭
                  </Link>
                </div>
              </Card>
            )}
          </section>
        </div>
      </div>

      {/* Match Celebration Modal */}
      {celebratingMatch && (
        <MatchCelebrationModal
          match={celebratingMatch}
          user={user}
          userPrimaryPhoto={userPrimaryPhoto}
          onClose={() => setCelebratingMatch(null)}
        />
      )}
    </PageContainer>
  )
}

function MatchCard({ match }: { match: MatchItem }) {
  const name = match.matched_user.full_name || match.matched_user.username || 'Raahi member'
  const photo = match.photos?.[0] || match.matched_user.photo_url || match.matched_user.photos?.[0]
  return (
    <Card className="matches-card card-enter" style={{ padding: '18px 20px', borderRadius: 20 }}>
      <div className="matches-card-top">
        <Avatar name={name} photo={photo} small />
        <span className="matches-status">Active match</span>
      </div>
      <h3 style={{ fontSize: '1.25rem', margin: '10px 0 2px' }}>
        {name}
        {match.age ? `, ${match.age}` : ''}
      </h3>
      <p className="matches-card-location" style={{ fontSize: '.8rem' }}>
        {match.city ? `⌖ ${match.city}` : 'A verified Raahi connection'}
      </p>
      {match.compatibility_score_status === 'legacy_placeholder' && (
        <p className="matches-legacy-score" style={{ fontSize: '.74rem' }}>Compatibility score unavailable</p>
      )}
      <p className="matches-card-note" style={{ fontSize: '.82rem', margin: '10px 0', lineHeight: 1.5 }}>{match.matched_user.bio || 'You both liked each other on Raahi.'}</p>
      <div className="matches-card-actions" style={{ marginTop: 12, gap: 8 }}>
        <Link className="matches-outline-button" to={`/matches/${match.id}/details`} style={{ minHeight: 36, padding: '6px 12px', fontSize: '.78rem' }}>
          Details
        </Link>
        <Link className="matches-primary-button" to={`/conversations/${match.chat_id}`} style={{ minHeight: 36, padding: '6px 14px', fontSize: '.78rem' }}>
          Chat 👋
        </Link>
      </div>
    </Card>
  )
}

export function MatchDetailPage() {
  const { matchId } = useParams()
  const { user, loading: authLoading } = useAuth()
  const [match, setMatch] = useState<MatchDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const id = Number(matchId)
    if (!user || !Number.isInteger(id) || id <= 0) return
    setLoading(true); setError('')
    try { setMatch(await fetchMatch(id)) }
    catch (reason) { setError(apiErrorMessage(reason, 'Match details could not be loaded.')) }
    finally { setLoading(false) }
  }, [matchId, user])

  useEffect(() => {
    if (user) void load()
    else setLoading(false)
  }, [load, user])

  if (authLoading) return <LoadingState label="Checking your Raahi session…" />
  if (!user) return <Navigate to="/login" replace />

  if (loading) return <LoadingState label="Loading match details…" />
  if (error) return <PageContainer className="matches-page"><PageError message={error} onRetry={() => void load()} /></PageContainer>
  if (!match) return <PageContainer className="matches-page"><PageError message="This match was not found." /></PageContainer>
  const name = match.matched_user.full_name || match.matched_user.username || 'Raahi member'
  const photo = match.photos?.[0] || match.matched_user.photo_url || match.matched_user.photos?.[0]
  return (
    <PageContainer className="matches-page page-enter">
      <Link className="matches-back-link" to="/matches"><span className="e e-swing">←</span> Back to matches</Link>
      <Card className="match-detail-card card-enter"><span className="matches-detail-glow" aria-hidden="true" /><p className="integration-eyebrow">ACTIVE MUTUAL MATCH</p><Avatar name={name} photo={photo} /><h1>{name}{match.age ? `, ${match.age}` : ''}</h1><p className="match-detail-location">{match.city || 'Raahi member'}{match.era ? ` · ${match.era}` : ''}{match.vibe_tag ? ` · ${match.vibe_tag}` : ''}</p><span className="matches-status"><span className="e e-tada">✓</span> Verified connection</span>
        <p className="match-detail-disclaimer">{match.matched_user.bio || 'You both liked each other on Raahi.'}</p>
        {match.profile_alignment && <p className="matches-alignment-note">Profile alignment is {match.profile_alignment.score == null ? 'unavailable' : `${Math.round(match.profile_alignment.score)}%`}. This is not a prediction of relationship success.</p>}
        {match.compatibility_score_status === 'legacy_placeholder' && <p className="matches-alignment-note">The legacy compatibility value is a placeholder; no compatibility score is being shown.</p>}
        <div className="match-detail-actions"><Link className="matches-primary-button bpulse" to={`/conversations/${match.chat_id}`}>Open conversation</Link><Link className="matches-outline-button" to="/matches">Back to matches</Link></div>
      </Card>
    </PageContainer>
  )
}

export function ConversationsListPanel({ selectedChatId }: { selectedChatId?: number | null }) {
  const { user, loading: authLoading } = useAuth()
  const { generation } = useTheme()
  const [chats, setChats] = useState<ChatSummary[]>([])
  const [matches, setMatches] = useState<MatchItem[]>([])
  const [chatError, setChatError] = useState('')
  const [search, setSearch] = useState('')

  const load = useCallback(async () => {
    if (!user) return
    setChatError('')
    try {
      const [chatList, matchList] = await Promise.all([
        fetchChats(),
        fetchMatches().catch(() => ({ matches: [] as MatchItem[] })),
      ])
      setChats(chatList)
      setMatches(matchList.matches || [])
    }
    catch (reason) { setChatError(apiErrorMessage(reason, 'Your conversations could not be loaded.')) }
  }, [user])

  useEffect(() => {
    if (user) void load()
  }, [load, user])

  useEffect(() => {
    const handleReload = () => { if (user) void load() }
    window.addEventListener('raahi:user-blocked', handleReload)
    window.addEventListener('raahi:match-ended', handleReload)
    return () => {
      window.removeEventListener('raahi:user-blocked', handleReload)
      window.removeEventListener('raahi:match-ended', handleReload)
    }
  }, [load, user])

  const eraModeLabel = generation === 'millennial' ? 'Millennial Mode' : generation === 'zillenial' ? 'Zillenial Mode' : 'Gen Z Mode'
  const eraModeIcon = generation === 'millennial' ? '⚡' : generation === 'zillenial' ? '🎭' : '💀'

  const filteredChats = useMemo(() => {
    return chats.filter(c => {
      const q = search.trim().toLowerCase()
      if (!q) return true
      const name = `${c.user?.full_name || ''} ${c.user?.username || ''}`.toLowerCase()
      const lastMsg = (c.last_message?.content || '').toLowerCase()
      return name.includes(q) || lastMsg.includes(q)
    })
  }, [chats, search])

  if (authLoading) return <LoadingState label="Checking your Raahi session…" />
  if (!user) {
    return <Navigate to="/login" replace />
  }

  const unreadCount = chats.filter(c => (c.unread_count ?? 0) > 0).length
  const chatCount = chats.length

  return (
    <div className="matches-shell conversations-sidebar-shell">
      {/* Top Header */}
      <header className="matches-topbar">
        <div className="matches-topbar-left">
          <span className="matches-count-badge" aria-label="Unread count">{unreadCount}</span>
          <div className="matches-title-wrap">
            <h1 className="matches-title">{eraModeIcon} Chat</h1>
            <p className="matches-subtitle">
              <span className="matches-live-dot" /> {chatCount} chats · {eraModeLabel}
            </p>
          </div>
        </div>
        <button type="button" className="matches-bell-btn" aria-label="Notifications">
          <span className="matches-bell-icon" aria-hidden="true">🔔</span>
        </button>
      </header>

      {chatError && <p className="chat-inline-error" role="alert">{chatError}</p>}

      {/* Search Input */}
      <div className="matches-search-wrap">
        <span className="matches-search-glass" aria-hidden="true">🔍</span>
        <input
          type="text"
          className="matches-search-input"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search matches..."
          aria-label="Search matches"
        />
      </div>

      {/* Scrollable Conversations Content Container */}
      <div className="matches-scroll-content">
        {/* NEW MATCHES Section */}
        {matches.length > 0 && (
          <section className="matches-section" aria-label="New matches">
            <h2 className="matches-section-heading">✨ NEW MATCHES</h2>
            <div className="new-matches-scroll">
              {matches.slice(0, 10).map(match => {
                const name = match.matched_user.full_name || match.matched_user.username || 'Match'
                const photo = match.photos?.[0] || match.matched_user.photo_url || match.matched_user.photos?.[0]
                const isSelected = selectedChatId === match.chat_id
                return (
                  <Link
                    key={match.id}
                    to={`/conversations/${match.chat_id}`}
                    className={`new-match-avatar-card${isSelected ? ' selected' : ''}`}
                    aria-label={`Open conversation with ${name}`}
                  >
                    <span className="new-match-pill">NEW</span>
                    <div className="new-match-ring" style={{ borderColor: 'var(--ep)', boxShadow: '0 0 14px rgba(216, 61, 180, 0.35)' }}>
                      <MatchAvatarImage
                        photo={photo}
                        name={name}
                        fallbackInitial={initials(name)}
                        className="new-match-avatar-img"
                      />
                      <span className="new-match-corner" aria-hidden="true">💖</span>
                    </div>
                    <span className="new-match-name">{name}</span>
                    <span className="new-match-status">{match.city || 'Active'}</span>
                  </Link>
                )
              })}
            </div>
          </section>
        )}

        {/* CONVERSATIONS Section */}
        <section className="matches-section" aria-label="Conversations">
          <h2 className="matches-section-heading">💬 CONVERSATIONS</h2>
          <div className="conversations-cards-column">
            {filteredChats.length > 0 ? (
              filteredChats.map(chat => {
                const isSelected = selectedChatId === chat.chat_id
                return (
                  <ConversationRow key={chat.chat_id} chat={chat} isSelected={isSelected} />
                )
              })
            ) : (
              <Card className="matches-empty-card" style={{ margin: '12px 0' }}>
                <span className="matches-empty-icon" aria-hidden="true">💬</span>
                <p className="integration-eyebrow">NO CONVERSATIONS YET</p>
                <h3 style={{ margin: '6px 0', fontSize: '1.1rem' }}>
                  {search.trim() ? `No chats found matching “${search}”` : 'Say hello to your matches'}
                </h3>
                <p style={{ fontSize: '.84rem' }}>
                  {search.trim()
                    ? 'Try searching with another name or keyword.'
                    : 'When you match with someone, your messages and chats will appear here.'}
                </p>
                {!search.trim() && (
                  <div className="matches-card-actions" style={{ justifyContent: 'center', marginTop: 12 }}>
                    <Link className="matches-primary-button" to="/matches">
                      View Matches 💖
                    </Link>
                  </div>
                )}
              </Card>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function ConversationEmptyPanel() {
  return (
    <div className="conversation-empty-panel">
      <div className="conversation-empty-card">
        <div className="conversation-empty-icon-ring" aria-hidden="true">
          <span className="conversation-empty-emoji">💬</span>
          <span className="conversation-empty-sparkle">✦</span>
        </div>
        <p className="integration-eyebrow">YOUR CONVERSATIONS</p>
        <h2 className="conversation-empty-title">Select a Conversation</h2>
        <p className="conversation-empty-desc">
          Choose someone from the list on the left to view your message history, send notes, and stay connected.
        </p>
        <div className="conversation-empty-actions">
          <Link className="matches-primary-button" to="/matches">
            View Matches 💖
          </Link>
          <Link className="matches-outline-button" to="/discover">
            Discover People 🧭
          </Link>
        </div>
        <div className="conversation-empty-pill">
          <span className="matches-live-dot" /> End-to-end connected in your era
        </div>
      </div>
    </div>
  )
}

export function ConversationsPage() {
  const { loading: authLoading } = useAuth()

  if (authLoading) return <LoadingState label="Checking your Raahi session…" />

  return (
    <PageContainer className="matches-page conversations-page page-enter">
      <div className="conversations-desktop-layout">
        <div className="conversations-panel-left">
          <ConversationsListPanel />
        </div>
        <div className="conversations-panel-right desktop-only">
          <ConversationEmptyPanel />
        </div>
      </div>
    </PageContainer>
  )
}

function ConversationRow({ chat, isSelected }: { chat: ChatSummary; isSelected?: boolean }) {
  const message = chat.last_message?.is_deleted ? 'Message deleted' : chat.last_message?.content || (chat.last_message?.message_type === 'image' ? 'Photo' : chat.last_message?.message_type === 'voice' ? 'Voice message' : 'Start a conversation')
  return (
    <Link className={`conversation-card-row${isSelected ? ' selected' : ''}`} to={`/conversations/${chat.chat_id}`}>
      <Avatar name={chat.user.full_name || chat.user.username} photo={chat.user.photo_url || chat.user.photos?.[0]} small />
      <div className="conv-row-body">
        <div className="conv-row-head">
          <strong className="conv-row-name">{chat.user.full_name || chat.user.username}{chat.user.is_online && <span className="online-indicator" aria-label="Online" />}</strong>
          {(chat.unread_count ?? 0) > 0 && <span className="conv-row-unread-dot" aria-label="Unread message" />}
        </div>
        <p className="conv-row-msg">{message}</p>
      </div>
      <div className="conv-row-end">
        <span>{chat.unread_count ? `${chat.unread_count} new` : chat.last_message?.created_at ? formatTime(chat.last_message.created_at) : ''}</span>
      </div>
    </Link>
  )
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function ProtectedAttachment({ message }: { message: ChatMessage }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    let objectUrl = ''
    void fetchProtectedBlob(`/attachments/${message.id}/content`).then(({ blob }) => {
      objectUrl = URL.createObjectURL(blob)
      if (alive) setUrl(objectUrl)
    }).catch(() => { if (alive) setError('File could not be loaded.') })
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [message.id])
  if (error) return <span className="chat-media-error">{error}</span>
  if (!url) return <span className="chat-media-loading">Loading protected file…</span>
  if (message.message_type === 'image') return <a className="chat-image-link" href={url} target="_blank" rel="noreferrer"><img src={url} alt={message.attachment_name || 'Shared image'} /></a>
  return <a className="chat-file-link" href={url} download={message.attachment_name || 'raahi-attachment'}>⇩ {message.attachment_name || 'Download attachment'}</a>
}

function ProtectedVoice({ message }: { message: ChatMessage }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let alive = true
    let objectUrl = ''
    void fetchProtectedBlob(`/attachments/${message.id}/content`).then(({ blob }) => {
      objectUrl = URL.createObjectURL(blob)
      if (alive) setUrl(objectUrl)
    }).catch(() => { if (alive) setUrl('') })
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [message.id])
  return url ? <audio className="chat-audio" controls preload="metadata" src={url}>Audio playback is not supported.</audio> : <span className="chat-media-loading">Loading voice message…</span>
}

function formatLastSeen(value: string | null | undefined, isOnline: boolean) {
  if (isOnline) return 'Active now'
  if (!value) return 'last seen 3d ago'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'last seen 3d ago'
  const diffMinutes = Math.floor((Date.now() - date.getTime()) / 60000)
  if (diffMinutes < 1) return 'Active just now'
  if (diffMinutes < 60) return `last seen ${diffMinutes}m ago`
  if (diffMinutes < 1440) return `last seen ${Math.floor(diffMinutes / 60)}h ago`
  return `last seen ${date.toLocaleDateString([], { month: 'short', day: 'numeric' })}`
}

function getEraLabel(era: string | null | undefined) {
  if (!era) return 'Gen Z 💀'
  const lower = era.toLowerCase()
  if (lower.includes('zill')) return 'Zillenial 🎭'
  if (lower.includes('mill')) return 'Millennial ⚡'
  return 'Gen Z 💀'
}

export function ConversationPage() {
  const navigate = useNavigate()
  const { conversationId } = useParams()
  const chatId = Number(conversationId)
  const { user, loading: authLoading } = useAuth()

  if (authLoading) return <LoadingState label="Checking your Raahi session…" />
  if (!user) {
    return <Navigate to="/login" replace />
  }

  const validChatId = Number.isInteger(chatId) && chatId > 0
  const token = getAuthToken()

  const [chat, setChat] = useState<ChatSummary | null>(null)
  const [match, setMatch] = useState<MatchItem | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [hasOlder, setHasOlder] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [connection, setConnection] = useState<'connecting' | 'connected' | 'reconnecting' | 'offline' | 'ended'>('connected')
  const [typing, setTyping] = useState(false)
  const [presence, setPresence] = useState(false)
  const [accessEnded, setAccessEnded] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [aiBusy, setAiBusy] = useState(false)
  const [aiError, setAiError] = useState('')
  const [suggestions, setSuggestions] = useState<{ suggestion_id?: number; style?: string; message: string }[]>([])
  const [aiResult, setAiResult] = useState<Record<string, unknown> | null>(null)
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null)
  const [selectedSuggestion, setSelectedSuggestion] = useState<{ id: number; text: string; eventKey: string } | null>(null)
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const [showAiDrawer, setShowAiDrawer] = useState(false)
  const [showBlockModal, setShowBlockModal] = useState(false)
  const [showReportModal, setShowReportModal] = useState(false)
  const [callNotice, setCallNotice] = useState<string | null>(null)
  const [recordDuration, setRecordDuration] = useState(0)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const retryTimerRef = useRef<number | null>(null)
  const typingTimerRef = useRef<number | null>(null)
  const reconnectCount = useRef(0)
  const intentionalClose = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const messageListRef = useRef<HTMLDivElement>(null)
  const isNearBottomRef = useRef(true)
  const prevMessageCountRef = useRef(0)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const recordStartedAt = useRef(0)
  const recordIntervalRef = useRef<number | null>(null)
  const [recording, setRecording] = useState(false)
  const [partnerPhotoError, setPartnerPhotoError] = useState(false)

  const partner = chat?.user
  const partnerUserId = partner?.id || match?.matched_user?.id || null
  const partnerName = partner?.full_name || partner?.username || match?.matched_user.full_name || match?.matched_user.username || 'Raahi member'
  const partnerPhoto = partner?.photo_url || partner?.photos?.[0] || match?.photos?.[0] || match?.matched_user.photo_url || match?.matched_user.photos?.[0] || null
  const partnerInitial = initials(partnerName)
  const ringColor = 'var(--ep)'
  const canUseExternalAi = Boolean(user?.ai_provider_processing_enabled)

  useEffect(() => {
    setPartnerPhotoError(false)
  }, [partnerPhoto])

  useEffect(() => {
    setDraft('')
    setReplyTo(null)
    setShowEmojiPicker(false)
    setShowAiDrawer(false)
  }, [chatId])

  const loadMessages = useCallback(async () => {
    if (!user || !validChatId) return
    try {
      const history = await fetchMessages(chatId)
      setMessages(history); setHasOlder(history.length === 200); setError('')
    }
    catch (reason) { setError(apiErrorMessage(reason, 'Messages could not be loaded.')) }
  }, [chatId, user, validChatId])

  useEffect(() => {
    if (!user || !validChatId) { setLoading(false); return }
    let alive = true
    setLoading(true); setError('')
    Promise.all([
      fetchChats().catch(() => [] as ChatSummary[]),
      fetchMatches().catch(() => ({ matches: [] as MatchItem[] })),
      fetchMessages(chatId),
    ])
      .then(([chats, matchesRes, history]) => {
        if (!alive) return
        setChat(chats.find(item => item.chat_id === chatId) ?? null)
        const matchData = (matchesRes.matches || []).find(item => item.chat_id === chatId) ?? null
        setMatch(matchData)
        setMessages(history)
        setHasOlder(history.length === 200)
      })
      .catch(reason => { if (alive) setError(apiErrorMessage(reason, 'This conversation could not be loaded.')) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [chatId, user, validChatId])

  const handleMessageListScroll = useCallback(() => {
    const el = messageListRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    isNearBottomRef.current = distanceFromBottom < 120
  }, [])

  useEffect(() => {
    const el = messageListRef.current
    if (!el) return
    const prevCount = prevMessageCountRef.current
    const currCount = messages.length
    prevMessageCountRef.current = currCount

    if (currCount === 0) return

    // On initial load: jump directly to bottom so latest messages are visible
    if (prevCount === 0) {
      el.scrollTop = el.scrollHeight
      return
    }

    // On new message arriving:
    const lastMsg = messages[messages.length - 1]
    const sentByMe = lastMsg && lastMsg.sender_id === (user?.id ?? 0)

    // Scroll smoothly to bottom only if sent by current user or user is already near bottom
    if (sentByMe || isNearBottomRef.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [messages, user?.id])

  useEffect(() => {
    if (!user || !token || !validChatId || accessEnded) return
    let alive = true
    intentionalClose.current = false
    const connect = () => {
      if (!alive || intentionalClose.current) return
      setConnection(reconnectCount.current ? 'reconnecting' : 'connecting')
      let socket: WebSocket
      try { socket = new WebSocket(chatSocketUrl(chatId, token)) }
      catch { scheduleReconnect(); return }
      socketRef.current = socket
      socket.onopen = () => { reconnectCount.current = 0; setConnection('connected'); void loadMessages() }
      socket.onmessage = event => {
        let payload: Record<string, unknown>
        try { payload = JSON.parse(String(event.data)) as Record<string, unknown> } catch { return }
        const type = payload.type
        if (type === 'ready') {
          const onlineIds = Array.isArray(payload.online_user_ids) ? payload.online_user_ids : []
          setPresence(Boolean(chat && onlineIds.includes(chat.user.id)))
          socket.send(JSON.stringify({ type: 'read_chat', chat_id: chatId }))
        } else if (type === 'message' || type === 'voice_message') {
          const incoming = payload as unknown as IncomingMessageEvent
          setMessages(current => reduceChatMessages(current, payload as Parameters<typeof reduceChatMessages>[1]))
          if (incoming.sender_id !== user.id && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'read', chat_id: chatId, message_id: incoming.message_id }))
          if (chat && incoming.sender_id === chat.user.id) setTyping(false)
        } else if (type === 'message_sent') {
          void loadMessages()
        } else if (type === 'message_failed') {
          setError(typeof payload.detail === 'string' ? payload.detail : 'Message could not be sent.')
        } else if (type === 'message_delivered') {
          setMessages(current => reduceChatMessages(current, payload as Parameters<typeof reduceChatMessages>[1]))
        } else if (type === 'message_read') {
          setMessages(current => reduceChatMessages(current, payload as Parameters<typeof reduceChatMessages>[1]))
        } else if (type === 'message_deleted') {
          setMessages(current => reduceChatMessages(current, payload as Parameters<typeof reduceChatMessages>[1]))
        } else if (type === 'message_reaction') {
          setMessages(current => reduceChatMessages(current, payload as Parameters<typeof reduceChatMessages>[1]))
        } else if (type === 'typing') {
          if (payload.user_id === chat?.user.id) {
            setTyping(true)
            if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current)
            typingTimerRef.current = window.setTimeout(() => setTyping(false), 2200)
          }
        } else if (type === 'presence') {
          if (payload.user_id === chat?.user.id) setPresence(payload.status === 'online' && payload.activity_status_enabled !== false)
        } else if (type === 'user_blocked' || type === 'match_unmatched') {
          setAccessEnded(true); setConnection('ended')
          setError('This match has ended. You can still read existing conversation history.')
          intentionalClose.current = true; socket.close()
        } else if (type === 'chat_deleted' && payload.deleted_for_user_id === user.id) {
          setAccessEnded(true); setConnection('ended'); setError('You removed this conversation from your list.')
        } else if (type === 'message_reaction_error' || type === 'message_delete_error' || type === 'error') {
          if (typeof payload.detail === 'string') setError(payload.detail)
        }
      }
      socket.onclose = event => {
        if (!alive || intentionalClose.current) return
        if (event.code === 1008) {
          setAccessEnded(true); setConnection('ended')
          setError('Chat access is no longer active. Existing history remains available.')
          return
        }
        scheduleReconnect()
      }
      socket.onerror = () => { if (socket.readyState !== WebSocket.CLOSED) socket.close() }
    }
    const scheduleReconnect = () => {
      if (!alive || intentionalClose.current) return
      reconnectCount.current += 1
      if (reconnectCount.current > 8) { setConnection('offline'); return }
      const delay = Math.min(15000, 600 * (2 ** Math.min(reconnectCount.current, 5)))
      setConnection('reconnecting')
      retryTimerRef.current = window.setTimeout(connect, delay)
    }
    connect()
    return () => {
      alive = false; intentionalClose.current = true
      if (retryTimerRef.current) window.clearTimeout(retryTimerRef.current)
      if (typingTimerRef.current) window.clearTimeout(typingTimerRef.current)
      socketRef.current?.close(); socketRef.current = null
    }
  }, [accessEnded, chat, chatId, loadMessages, token, user, validChatId])

  useEffect(() => () => {
    if (recordIntervalRef.current) window.clearInterval(recordIntervalRef.current)
    mediaRecorderRef.current?.stop()
    mediaStreamRef.current?.getTracks().forEach(track => track.stop())
  }, [])

  function handleTyping(value: string) {
    setDraft(value)
    if (selectedSuggestion && value !== selectedSuggestion.text) setSelectedSuggestion(selectedSuggestion)
    const socket = socketRef.current
    if (value.trim() && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'typing', chat_id: chatId }))
  }

  function insertEmoji(emoji: string) {
    setDraft(current => current + emoji)
    inputRef.current?.focus()
  }

  function handleCall() {
    setCallNotice('Raahi voice & video calls are coming soon to your era!')
    window.setTimeout(() => setCallNotice(null), 3500)
  }

  async function submitMessage(event?: FormEvent) {
    if (event) event.preventDefault()
    const content = draft.trim()
    if (!content || busy || accessEnded) return

    setBusy(true); setError('')
    try {
      const selected = selectedSuggestion
      if (selected && selected.id && content !== selected.text) {
        await trackSuggestionEvent(selected.id, 'edited', `${selected.eventKey}-edited`, { changed: true })
      }
      const message = await sendTextMessage(chatId, content, replyTo?.id)
      setMessages(current => mergeChatMessage(current, message))
      setDraft(''); setReplyTo(null); setSelectedSuggestion(null); setShowEmojiPicker(false)
      if (selected) {
        try { await trackSuggestionEvent(selected.id, 'sent', `${selected.eventKey}-sent`, { message_id: message.id, edited: content !== selected.text }) }
        catch { setAiError('Your message was sent, but its AI suggestion event could not be recorded.') }
      }
    } catch (reason) { setError(apiErrorMessage(reason, 'Message could not be sent.')) }
    finally { setBusy(false) }
  }

  async function removeMessage(message: ChatMessage) {
    setError('')
    try {
      await deleteMessage(message.id)
      setMessages(current => current.map(item => item.id === message.id ? { ...item, is_deleted: true, content: null, attachment_name: null } : item))
    } catch (reason) { setError(apiErrorMessage(reason, 'Message could not be deleted.')) }
  }

  async function loadOlderMessages() {
    const firstId = messages[0]?.id
    if (!firstId || loadingOlder) return
    setLoadingOlder(true)
    try {
      const older = await fetchMessages(chatId, 200, firstId)
      setMessages(current => older.reduce((all, message) => mergeChatMessage(all, message), current))
      if (older.length < 200) setHasOlder(false)
    } catch (reason) { setError(apiErrorMessage(reason, 'Earlier messages could not be loaded.')) }
    finally { setLoadingOlder(false) }
  }

  async function removeConversation() {
    if (!window.confirm('Remove this conversation from your list? The other person will keep their conversation history.')) return
    try { await deleteConversation(chatId); window.location.assign('/conversations') }
    catch (reason) { setError(apiErrorMessage(reason, 'Conversation could not be removed.')) }
  }

  async function sendAttachment(file?: File) {
    if (!file || accessEnded) return
    setUploadProgress(0); setError('')
    try {
      const message = await uploadAttachment(chatId, file, '', setUploadProgress)
      setMessages(current => mergeChatMessage(current, message))
    } catch (reason) { setError(apiErrorMessage(reason, 'Attachment upload failed.')) }
    finally { window.setTimeout(() => setUploadProgress(null), 500) }
  }

  function cancelRecording() {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.ondataavailable = null
      mediaRecorderRef.current.onstop = null
      mediaRecorderRef.current.stop()
      mediaStreamRef.current?.getTracks().forEach(track => track.stop())
      mediaStreamRef.current = null
    }
    if (recordIntervalRef.current) window.clearInterval(recordIntervalRef.current)
    setRecording(false)
    setRecordDuration(0)
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Voice recording is not supported by this browser. You can attach an audio file instead.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm'
      const recorder = new MediaRecorder(stream, { mimeType })
      const chunks: BlobPart[] = []
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      recorder.onstop = async () => {
        if (recordIntervalRef.current) window.clearInterval(recordIntervalRef.current)
        stream.getTracks().forEach(track => track.stop())
        mediaStreamRef.current = null
        const duration = Math.max(1, Math.min(300, Math.ceil((Date.now() - recordStartedAt.current) / 1000)))
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
        if (!blob.size) return
        const file = new File([blob], `voice-${Date.now()}.webm`, { type: 'audio/webm' })
        setUploadProgress(0); setError('')
        try {
          const result = await uploadVoice(chatId, file, duration, setUploadProgress)
          setMessages(current => mergeChatMessage(current, result.message))
        } catch (reason) { setError(apiErrorMessage(reason, 'Voice message upload failed.')) }
        finally { window.setTimeout(() => setUploadProgress(null), 500) }
      }
      recordStartedAt.current = Date.now()
      setRecordDuration(0)
      recordIntervalRef.current = window.setInterval(() => {
        setRecordDuration(Math.floor((Date.now() - recordStartedAt.current) / 1000))
      }, 1000)
      mediaRecorderRef.current = recorder
      recorder.start(); setRecording(true)
      window.setTimeout(() => { if (recorder.state === 'recording') { setRecording(false); recorder.stop() } }, 300000)
    } catch { setError('Microphone access was not granted. Check browser permissions and try again.') }
  }

  function stopRecording() {
    if (recordIntervalRef.current) window.clearInterval(recordIntervalRef.current)
    if (mediaRecorderRef.current?.state === 'recording') { setRecording(false); mediaRecorderRef.current.stop() }
  }

  async function runAi(kind: 'suggestions' | 'coach' | 'insights') {
    setAiBusy(true); setAiError(''); setAiResult(null)
    try {
      if (kind === 'suggestions') setSuggestions((await fetchSuggestions(chatId)).suggestions)
      else setAiResult(kind === 'coach' ? await fetchCoach(chatId) : await fetchInsights(chatId))
    } catch (reason) { setAiError(apiErrorMessage(reason, 'AI assistance is unavailable right now.')) }
    finally { setAiBusy(false) }
  }

  async function selectSuggestion(suggestion: { suggestion_id?: number; message: string }) {
    if (suggestion.suggestion_id) {
      const eventKey = `selected-${crypto.randomUUID()}`
      try { await trackSuggestionEvent(suggestion.suggestion_id, 'selected', eventKey) }
      catch (reason) { setAiError(apiErrorMessage(reason, 'This suggestion can no longer be used.')); return }
      setSelectedSuggestion({ id: suggestion.suggestion_id, text: suggestion.message, eventKey })
    }
    setDraft(suggestion.message)
    setShowAiDrawer(false)
    inputRef.current?.focus()
  }

  function sendReaction(message: ChatMessage) {
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'message_reaction', chat_id: chatId, message_id: message.id, reaction: '❤️', request_id: crypto.randomUUID() }))
  }

  if (authLoading) return <LoadingState label="Checking your Raahi session…" />
  if (!user) return <AuthGate />
  if (!validChatId) {
    return (
      <PageContainer className="matches-page conversation-page">
        <div className="conversations-desktop-layout">
          <div className="conversations-panel-left desktop-only">
            <ConversationsListPanel selectedChatId={null} />
          </div>
          <div className="conversations-panel-right">
            <div className="conversation-empty-panel">
              <Card className="matches-empty-card" style={{ marginTop: 20 }}>
                <span className="matches-empty-icon" aria-hidden="true">💬</span>
                <h2>Conversation not found</h2>
                <p>This conversation is not available or has been removed.</p>
                <div className="matches-card-actions" style={{ justifyContent: 'center', marginTop: 14 }}>
                  <Link className="matches-primary-button" to="/discover">
                    Find people on Discover
                  </Link>
                </div>
              </Card>
            </div>
          </div>
        </div>
      </PageContainer>
    )
  }
  if (loading) {
    return (
      <PageContainer className="matches-page conversation-page">
        <div className="conversations-desktop-layout">
          <div className="conversations-panel-left desktop-only">
            <ConversationsListPanel selectedChatId={chatId} />
          </div>
          <div className="conversations-panel-right">
            <div className="conversation-empty-panel">
              <LoadingState label="Opening conversation…" />
            </div>
          </div>
        </div>
      </PageContainer>
    )
  }
  if (error && !messages.length && !chat) return <PageContainer className="matches-page"><PageError message={error} onRetry={() => void loadMessages()} /></PageContainer>

  return (
    <PageContainer className="matches-page conversation-page">
      <div className="conversations-desktop-layout">
        <div className="conversations-panel-left desktop-only">
          <ConversationsListPanel selectedChatId={chatId} />
        </div>
        <div className="conversations-panel-right">
          <section className="conversation-shell page-enter" aria-label={`Conversation with ${partnerName}`}>
            {/* Exact Header Reproduction */}
            <header className="conversation-header">
              <Link className="chat-circle-btn chat-back-btn" to="/conversations" aria-label="Back to conversations">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M19 12H5M12 19l-7-7 7-7"/>
                </svg>
              </Link>
          <div className="chat-header-avatar-wrap">
            <div className="chat-avatar-ring" style={{ borderColor: ringColor, boxShadow: `0 0 12px ${ringColor}66`, overflow: 'hidden' }}>
              {partnerPhoto && !partnerPhotoError ? (
                <img
                  src={resolveMediaUrl(partnerPhoto)}
                  alt={partnerName}
                  className="chat-avatar-photo"
                  onError={() => setPartnerPhotoError(true)}
                />
              ) : (
                <span className="chat-avatar-letter">{partnerInitial}</span>
              )}
            </div>
          </div>
          <div className="chat-header-copy">
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <h1 className="chat-header-title">{partnerName}</h1>
            </div>
            <p className="chat-header-status-line">
              <span className="chat-seen-eye">👁</span> {presence ? 'Active now' : partner?.last_seen ? formatLastSeen(partner.last_seen, false) : 'Active mutual match'}
            </p>
            <p className="chat-header-vibe-line">
              <span>{getEraLabel(match?.era)} • {match?.compatibility_score ? `${match.compatibility_score}% match` : 'Mutual match'}</span>
            </p>
          </div>
          <div className="chat-header-actions">
            <button type="button" className="chat-circle-btn chat-call-btn" title="Start voice call" aria-label="Start voice call" onClick={handleCall}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>
              </svg>
            </button>
            {partnerUserId && (
              <SafetyMenuDropdown
                onOpenReport={() => setShowReportModal(true)}
                onOpenBlock={() => setShowBlockModal(true)}
                ariaLabel={`Safety options for conversation with ${partnerName}`}
              />
            )}
            <Link to="/settings" className="chat-header-settings-pill" title="Settings" aria-label="Settings">
              <span className="chat-settings-icon" aria-hidden="true">⚙</span> Settings
            </Link>
          </div>
        </header>

        {partnerUserId && (
          <>
            <BlockConfirmationModal
              isOpen={showBlockModal}
              targetUserId={partnerUserId}
              targetName={partnerName}
              isMatchOrChat={true}
              onClose={() => setShowBlockModal(false)}
              onSuccess={() => {
                window.dispatchEvent(new CustomEvent('raahi:user-blocked', { detail: { userId: partnerUserId, chatId } }))
                window.dispatchEvent(new CustomEvent('raahi:match-ended', { detail: { chatId } }))
                navigate('/conversations')
              }}
            />
            <ReportUserModal
              isOpen={showReportModal}
              targetUserId={partnerUserId}
              targetName={partnerName}
              onClose={() => setShowReportModal(false)}
              onSuccess={(msg) => {
                setCallNotice(msg)
                window.setTimeout(() => setCallNotice(null), 3500)
              }}
            />
          </>
        )}

        {callNotice && <div className="chat-toast" role="status">{callNotice}</div>}
        {accessEnded && <div className="conversation-disclaimer"><span aria-hidden="true">✦</span><p>This match has ended. History remains readable; sending, AI tools, and new media are disabled.</p><button type="button" className="chat-remove-ended-btn" onClick={() => void removeConversation()}>Remove conversation</button></div>}
        {error && <p className="chat-inline-error" role="alert">{error}</p>}

        {/* Conversation Message Area */}
        <div
          ref={messageListRef}
          onScroll={handleMessageListScroll}
          className="conversation-message-list"
          role="log"
          aria-label="Conversation messages"
          aria-live="polite"
        >
          {hasOlder && <button type="button" className="chat-load-older" onClick={() => void loadOlderMessages()} disabled={loadingOlder}>{loadingOlder ? 'Loading earlier messages…' : 'Load earlier messages'}</button>}

          {/* Centered Match Introduction Card */}
          <div className="match-intro-card card-enter">
            <div className="intro-avatar-container">
              <div className="intro-avatar-halo" aria-hidden="true" style={{ background: `radial-gradient(circle, ${ringColor}66, transparent 70%)` }} />
              <div className="intro-avatar-circle" style={{ borderColor: ringColor, boxShadow: `0 0 22px ${ringColor}55`, overflow: 'hidden' }}>
                {partnerPhoto && !partnerPhotoError ? (
                  <img
                    src={resolveMediaUrl(partnerPhoto)}
                    alt={partnerName}
                    className="intro-avatar-photo"
                    onError={() => setPartnerPhotoError(true)}
                  />
                ) : (
                  <span className="intro-avatar-letter">{partnerInitial}</span>
                )}
              </div>
            </div>
            <h2 className="intro-name">{partnerName}</h2>
            <p className="intro-subtext">
              <span>{getEraLabel(match?.era)}</span>
              <span className="intro-dot">·</span>
              <span className="intro-seen"><span className="chat-seen-eye">👁</span> {presence ? 'Active now' : partner?.last_seen ? formatLastSeen(partner.last_seen, false) : 'Active'}</span>
            </p>
            <div className="intro-hearts" aria-hidden="true">
              <span className="intro-heart e-float">💗</span>
              <span className="intro-heart e-orbit">💫</span>
              <span className="intro-heart e-float e-delay-1">💖</span>
            </div>
            <div className="intro-connected-pill">
              <span>🎉 You two are connected — say hi!</span>
            </div>
          </div>

          {messages.map(message => (
            <article className={`message-row ${message.sender_id === (user?.id ?? 0) ? 'outgoing' : 'incoming'}`} key={message.id}>
              {message.sender_id !== (user?.id ?? 0) && (
                <div className="message-partner-avatar-ring" style={{ borderColor: ringColor, overflow: 'hidden' }}>
                  {partnerPhoto && !partnerPhotoError ? (
                    <img
                      src={resolveMediaUrl(partnerPhoto)}
                      alt={partnerName}
                      className="message-partner-avatar-img"
                      onError={() => setPartnerPhotoError(true)}
                    />
                  ) : (
                    <span>{partnerInitial}</span>
                  )}
                </div>
              )}
              <div className="message-bubble">
                {message.is_deleted ? <p className="deleted-message">Message deleted</p> : <>
                  {message.reply_to_id && <span className="reply-indicator">↳ Reply to message #{message.reply_to_id}</span>}
                  {message.message_type === 'image' || message.message_type === 'file' ? <><ProtectedAttachment message={message} />{message.content && <p>{message.content}</p>}</> : message.message_type === 'voice' ? <ProtectedVoice message={message} /> : <p>{message.content}</p>}
                </>}
                <div className="message-meta">
                  <time>{message.created_at ? new Date(message.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : ''}</time>
                  {message.sender_id === (user?.id ?? 0) && (
                    <span className={`message-receipt ${message.is_read ? 'read' : message.is_delivered ? 'delivered' : 'sent'}`}>
                      {message.is_read ? '✓✓' : message.is_delivered ? '✓✓' : '✓'}
                    </span>
                  )}
                </div>
                {message.reactions.length > 0 && <div className="message-reactions">{message.reactions.map((reaction, index) => <span key={`${reaction.user_id}-${index}`}>{reaction.reaction}</span>)}</div>}
                {!message.is_deleted && <div className="message-actions">
                  <button type="button" onClick={() => setReplyTo(message)} aria-label="Reply to message">↩</button>
                  <button type="button" onClick={() => sendReaction(message)} disabled={accessEnded || connection !== 'connected'} aria-label="React with heart">♡</button>
                  {message.sender_id === (user?.id ?? 0) && <button type="button" onClick={() => void removeMessage(message)} aria-label="Delete message for everyone">⌫</button>}
                </div>}
              </div>
            </article>
          ))}
          {typing && (
            <div className="message-row incoming chat-typing-row" role="status">
              <div className="message-partner-avatar-ring" style={{ borderColor: ringColor }}>
                <span>{partnerInitial}</span>
              </div>
              <div className="message-bubble chat-typing-bubble">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Emoji Quick Drawer */}
        {showEmojiPicker && (
          <div className="chat-emoji-drawer">
            {['💖', '🔥', '✨', '👀', '😂', '🥰', '👋', '💀', '🥺', '💯', '🥂', '⚡'].map(emoji => (
              <button type="button" key={emoji} className="chat-emoji-btn" onClick={() => insertEmoji(emoji)}>
                {emoji}
              </button>
            ))}
          </div>
        )}

        {/* AI Suggestions / Coach Drawer */}
        {showAiDrawer && (
          <div className="chat-ai-drawer" aria-live="polite">
            <div className="chat-ai-header">
              <span className="chat-ai-title">✦ Raahi AI Assist</span>
              <div className="chat-ai-actions">
                <button type="button" className="chat-ai-tab" onClick={() => void runAi('suggestions')} disabled={aiBusy || !canUseExternalAi}>Suggestions</button>
                <button type="button" className="chat-ai-tab" onClick={() => void runAi('coach')} disabled={aiBusy || !canUseExternalAi}>Coach</button>
                <button type="button" className="chat-ai-tab" onClick={() => void runAi('insights')} disabled={aiBusy}>Insights</button>
                <button type="button" className="chat-ai-close" onClick={() => setShowAiDrawer(false)}>×</button>
              </div>
            </div>
            {aiBusy && <p className="chat-muted chat-ai-loading">Generating insights…</p>}
            {aiError && <p className="chat-inline-error">{aiError}</p>}
            {suggestions.length > 0 && (
              <div className="chat-suggestions-list">
                {suggestions.map((suggestion, index) => (
                  <button type="button" className="chat-suggestion" key={suggestion.suggestion_id ?? index} onClick={() => void selectSuggestion(suggestion)}>
                    <span>{suggestion.style || 'Vibe'}</span>
                    {suggestion.message}
                  </button>
                ))}
              </div>
            )}
            {aiResult && <pre className="chat-ai-result">{JSON.stringify(aiResult, null, 2)}</pre>}
          </div>
        )}

        {/* Voice Recording Active Bar */}
        {recording && (
          <div className="chat-recording-banner" role="status">
            <span className="recording-indicator-dot" />
            <span className="recording-text">Recording voice note… {Math.floor(recordDuration / 60)}:{String(recordDuration % 60).padStart(2, '0')}</span>
            <button type="button" className="recording-cancel-btn" onClick={cancelRecording}>Cancel</button>
          </div>
        )}

        {uploadProgress !== null && <div className="chat-upload-progress" role="status"><span>Uploading… {uploadProgress}%</span><progress max="100" value={uploadProgress} /></div>}
        {replyTo && <div className="chat-reply-banner"><span>Replying to message #{replyTo.id}</span><button type="button" onClick={() => setReplyTo(null)} aria-label="Cancel reply">×</button></div>}

        {/* Exact 5-Control Message Composer */}
        {!accessEnded ? (
          <form className="conversation-composer" onSubmit={submitMessage}>
            {/* 1. Emoji button */}
            <button
              type="button"
              className={`chat-composer-btn chat-emoji-toggle${showEmojiPicker ? ' active' : ''}`}
              title="Emoji picker"
              aria-label="Emoji picker"
              onClick={() => setShowEmojiPicker(!showEmojiPicker)}
            >
              😊
            </button>

            {/* 2. Rounded message input */}
            <div className="conversation-composer-field">
              <textarea
                ref={inputRef}
                rows={1}
                value={draft}
                onChange={event => handleTyping(event.currentTarget.value)}
                onKeyDown={event => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void submitMessage()
                  }
                }}
                placeholder="Message..."
                aria-label="Write a message"
                maxLength={2000}
                disabled={busy}
              />
            </div>

            {/* 3. AI sparkle button */}
            <button
              type="button"
              className={`chat-composer-btn chat-ai-sparkle-btn${showAiDrawer ? ' active' : ''}${aiBusy ? ' busy' : ''}`}
              title="Raahi AI Assist"
              aria-label="Raahi AI Assist"
              onClick={() => {
                const next = !showAiDrawer
                setShowAiDrawer(next)
                if (next && !suggestions.length && !aiBusy) void runAi('suggestions')
              }}
            >
              <span className="ai-sparkle-glyph" aria-hidden="true">✦</span>
            </button>

            {/* 4. Attachment button */}
            <label className="chat-composer-btn chat-attach-btn" title="Attach file or photo" aria-label="Attach file or photo">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
              </svg>
              <input
                type="file"
                className="sr-only"
                accept="image/jpeg,image/png,image/webp,application/pdf,text/plain"
                disabled={uploadProgress !== null}
                onChange={event => {
                  const file = event.currentTarget.files?.[0]
                  if (file) {
                    void sendAttachment(file)
                  }
                  event.currentTarget.value = ''
                }}
              />
            </label>

            {/* 5. Microphone button */}
            <button
              type="button"
              className={`chat-composer-btn chat-mic-btn${recording ? ' recording' : ''}`}
              title={recording ? 'Stop and send voice message' : 'Record voice message'}
              aria-label={recording ? 'Stop and send voice note' : 'Record voice message'}
              disabled={uploadProgress !== null}
              onClick={recording ? stopRecording : () => void startRecording()}
            >
              {recording ? (
                <span className="mic-stop-square" aria-hidden="true" />
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                  <line x1="12" y1="19" x2="12" y2="23"/>
                  <line x1="8" y1="23" x2="16" y2="23"/>
                </svg>
              )}
            </button>

            {/* 6. Send button */}
            <button
              type="submit"
              className="chat-composer-btn chat-send-btn"
              title="Send message"
              aria-label="Send message"
              disabled={!draft.trim() || busy || accessEnded}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ transform: 'translateX(1px)' }}>
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </form>
        ) : (
          <div className="conversation-composer chat-readonly-note">Conversation is read-only</div>
        )}
          </section>
        </div>
      </div>
    </PageContainer>
  )
}

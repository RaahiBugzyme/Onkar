import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { fetchPublicProfile, type FeedProfile, type PublicProfile } from '../api/discover'
import { ApiError, resolveMediaUrl } from '../api/client'
import { fetchChats } from '../api/chat'
import { Card } from '../components/Card'
import { LoadingState } from '../components/LoadingState'
import { PageContainer } from '../components/PageContainer'
import { generationThemes, type GenerationId } from '../data/generations'
import { useTheme } from '../state/ThemeContext'
import { useDiscover, type DiscoverAction } from '../state/DiscoverContext'
import { useAuth } from '../state/AuthContext'
import { BlockConfirmationModal, ReportUserModal, SafetyMenuDropdown } from '../components/SafetyModals'
import '../styles/discover.css'

const eraLabels: Record<string, string> = { genz: 'Gen Z', zillenial: 'Zillenial', millennial: 'Millennial' }

interface UnifiedCandidate {
  id: number
  name: string
  age?: number | null
  city: string
  era: GenerationId
  profession?: string | null
  education?: string | null
  bio?: string | null
  vibeTag?: string | null
  tags?: string[]
  relationshipIntentions?: string | null
  completenessCategory?: string
  completenessScore?: number
  photos: string[]
  compatibilityScore?: number | null
  isVerified?: boolean
  isDemo: boolean
  chatId?: number
  ringColor?: string
  cornerEmoji?: string
  initials?: string
  isSuperLike?: boolean
}

function normalizeFeedProfile(feed: FeedProfile): UnifiedCandidate {
  const name = feed.full_name || feed.username || 'Raahi member'
  const era = (feed.era in eraLabels ? feed.era : 'genz') as GenerationId
  const initial = name.trim()[0]?.toUpperCase() ?? 'R'
  const ring = era === 'zillenial' ? '#f59e0b' : era === 'millennial' ? '#06b6d4' : '#a855f7'
  const dummySvg = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500" width="100%" height="100%"><rect width="100%" height="100%" fill="%23140a28"/><circle cx="200" cy="220" r="90" fill="${encodeURIComponent(ring)}" fill-opacity="0.25"/><circle cx="200" cy="220" r="75" fill="%231e0f38" stroke="${encodeURIComponent(ring)}" stroke-width="3"/><text x="200" y="250" font-family="sans-serif" font-size="70" font-weight="bold" fill="%23ffffff" text-anchor="middle">${initial}</text></svg>`

  const feedPhotos = feed.photos && feed.photos.length > 0 ? feed.photos : (feed.photo_url ? [feed.photo_url] : [dummySvg])
  const feedInterests = feed.interests && feed.interests.length > 0 ? feed.interests : (feed.vibe_tag ? [feed.vibe_tag] : ['vibe check passed', 'genuine connection'])

  return {
    id: feed.user_id,
    name,
    age: feed.age ?? undefined,
    city: feed.city,
    era,
    profession: feed.profession ?? null,
    education: feed.education ?? null,
    bio: feed.bio,
    vibeTag: feed.vibe_tag,
    tags: feedInterests,
    relationshipIntentions: feed.relationship_intentions ?? null,
    completenessCategory: 'complete',
    completenessScore: 100,
    photos: feedPhotos,
    compatibilityScore: feed.compatibility_score != null ? Math.round(feed.compatibility_score) : null,
    isVerified: Boolean(feed.is_face_verified && feed.is_id_verified),
    isDemo: false,
    chatId: feed.user_id,
    ringColor: ring,
    cornerEmoji: era === 'zillenial' ? '🎭' : era === 'millennial' ? '⚡' : '💀',
    initials: initial,
  }
}

function ProfileCard({
  candidate,
  onAction,
  onOpenDetails,
  busy,
  isRestored = false,
}: {
  candidate: UnifiedCandidate
  onAction: (action: DiscoverAction) => void
  onOpenDetails: () => void
  busy: boolean
  isRestored?: boolean
}) {
  const pointer = useRef<{ x: number; y: number } | null>(null)
  const isDragging = useRef(false)
  const dragDistance = useRef(0)
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 })
  const [activePhoto, setActivePhoto] = useState(0)

  const photoCount = candidate.photos.length || 1

  function handlePhotoTap(direction: 'left' | 'right', e: React.MouseEvent) {
    e.stopPropagation()
    if (direction === 'left') {
      setActivePhoto(prev => (prev > 0 ? prev - 1 : photoCount - 1))
    } else {
      setActivePhoto(prev => (prev < photoCount - 1 ? prev + 1 : 0))
    }
  }

  function start(event: PointerEvent<HTMLElement>) {
    if ((event.target as Element).closest('button, a, .photo-tap-zone, .discover-info-btn')) return
    pointer.current = { x: event.clientX, y: event.clientY }
    isDragging.current = false
    dragDistance.current = 0
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function move(event: PointerEvent<HTMLElement>) {
    if (!pointer.current) return
    const dx = event.clientX - pointer.current.x
    const dy = event.clientY - pointer.current.y
    const dist = Math.hypot(dx, dy)
    dragDistance.current = Math.max(dragDistance.current, dist)
    if (dist > 8) {
      isDragging.current = true
    }
    setDragOffset({
      x: dx,
      y: dy,
    })
  }

  function end() {
    if (!pointer.current) return
    const { x, y } = dragOffset
    pointer.current = null

    if (x > 85) {
      onAction('like')
    } else if (x < -85) {
      onAction('pass')
    } else if (y < -80 && Math.abs(x) < 70) {
      onAction('superlike')
    }
    setDragOffset({ x: 0, y: 0 })
  }

  function handleCardClick(event: React.MouseEvent<HTMLElement>) {
    if (dragDistance.current > 8 || isDragging.current) return
    if ((event.target as Element).closest('button, a, .photo-tap-zone, .discover-info-btn')) return
    onOpenDetails()
  }

  const { x, y } = dragOffset
  const isSuperDrag = y < -35 && Math.abs(x) < 55

  const rotation = x * 0.08
  const currentPhotoUrl = resolveMediaUrl(candidate.photos[activePhoto] || candidate.photos[0])
  const theme = generationThemes[candidate.era] || generationThemes.genz

  return (
    <article
      className={`discover-live-card card-enter${isRestored ? ' card-rewind-enter' : ''}`}
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onClick={handleCardClick}
      style={{
        transform: `translate(${x}px, ${y}px) rotate(${rotation}deg)`,
        transition: pointer.current ? 'none' : 'transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)',
        cursor: 'pointer',
      }}
      aria-label={`Profile card for ${candidate.name}`}
    >
      {/* Dynamic Action Stamps */}
      {x > 25 && !isSuperDrag && <span className="discover-drag-label like overlay-like">LIKE</span>}
      {x < -25 && !isSuperDrag && <span className="discover-drag-label pass overlay-nope">PASS</span>}
      {isSuperDrag && <span className="discover-drag-label super">SUPER LIKE ⭐</span>}

      {/* Multi-Photo Carousel */}
      <div className="discover-card-photo-wrap">
        {photoCount > 1 && (
          <div className="photo-bars-indicators" aria-hidden="true">
            {Array.from({ length: photoCount }).map((_, idx) => (
              <span
                key={idx}
                className={`photo-bar-segment${idx === activePhoto ? ' active' : ''}`}
              />
            ))}
          </div>
        )}

        {/* Small circular information (i) icon at top-right corner */}
        <button
          type="button"
          className="discover-info-btn"
          aria-label={`View full profile of ${candidate.name}`}
          title="View full profile"
          onClick={(e) => {
            e.stopPropagation()
            onOpenDetails()
          }}
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
        </button>

        <img
          src={currentPhotoUrl}
          alt={`${candidate.name} photo ${activePhoto + 1}`}
          className="discover-card-photo-img"
          draggable={false}
          onError={e => {
            const initial = candidate.name.trim()[0]?.toUpperCase() ?? 'R'
            const ring = candidate.era === 'zillenial' ? '#f59e0b' : candidate.era === 'millennial' ? '#06b6d4' : '#a855f7'
            e.currentTarget.src = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500" width="100%" height="100%"><rect width="100%" height="100%" fill="%23140a28"/><circle cx="200" cy="220" r="90" fill="${encodeURIComponent(ring)}" fill-opacity="0.25"/><circle cx="200" cy="220" r="75" fill="%231e0f38" stroke="${encodeURIComponent(ring)}" stroke-width="3"/><text x="200" y="250" font-family="sans-serif" font-size="70" font-weight="bold" fill="%23ffffff" text-anchor="middle">${initial}</text></svg>`
          }}
        />

        {/* Tap zones for switching photos */}
        <div
          className="photo-tap-zone left"
          title="Previous photo"
          onClick={e => handlePhotoTap('left', e)}
          role="button"
          tabIndex={-1}
          aria-label="Previous photo"
        />
        <div
          className="photo-tap-zone right"
          title="Next photo"
          onClick={e => handlePhotoTap('right', e)}
          role="button"
          tabIndex={-1}
          aria-label="Next photo"
        />
      </div>

      {/* Card Content & Details */}
      <div className="discover-live-copy">
        <div className="discover-card-title-row">
          <div className="discover-title-info">
            <h2 className="discover-card-name">
              {candidate.name}{candidate.age ? `, ${candidate.age}` : ''}
              {candidate.isVerified && (
                <span className="discover-verified-check" title="Verified Connection" aria-label="Verified">
                  ✓
                </span>
              )}
            </h2>
            <p className="discover-card-meta">
              <span className="discover-meta-pin" aria-hidden="true">⌖</span> {candidate.city} · {candidate.vibeTag || (eraLabels[candidate.era] ?? candidate.era)}
            </p>
          </div>
          <span className="discover-era-pill" style={{ borderColor: `${candidate.ringColor}66`, color: candidate.ringColor }}>
            <span className={`e ${theme.emojiAnimation}`} aria-hidden="true">
              {candidate.cornerEmoji || theme.emoji}
            </span>{' '}
            {eraLabels[candidate.era] ?? candidate.era}
          </span>
        </div>

        {candidate.bio && <p className="discover-bio-text">{candidate.bio}</p>}

        {candidate.tags && candidate.tags.length > 0 && (
          <div className="discover-chips-row">
            {candidate.tags.slice(0, 4).map((tag, i) => (
              <span key={i} className="discover-chip">{tag}</span>
            ))}
          </div>
        )}
      </div>

      {busy && <div className="discover-card-busy" role="status">Saving your action…</div>}
    </article>
  )
}

export function DiscoverPage() {
  const { user, loading: authLoading } = useAuth()
  const {
    currentProfile: liveProfile,
    profiles: liveProfiles,
    loading: liveLoading,
    error: liveError,
    recordAction,
    refresh,
  } = useDiscover()
  const { generation } = useTheme()
  const navigate = useNavigate()

  const [busy, setBusy] = useState(false)
  const [feedbackToast, setFeedbackToast] = useState<string | null>(null)
  const [matchedCandidate, setMatchedCandidate] = useState<UnifiedCandidate | null>(null)
  const [detailsCandidate, setDetailsCandidate] = useState<UnifiedCandidate | null>(null)
  const [showCandidateBlock, setShowCandidateBlock] = useState(false)
  const [showCandidateReport, setShowCandidateReport] = useState(false)

  useEffect(() => {
    const handleBlocked = () => {
      void refresh()
    }
    window.addEventListener('raahi:user-blocked', handleBlocked)
    return () => {
      window.removeEventListener('raahi:user-blocked', handleBlocked)
    }
  }, [refresh])

  if (authLoading) {
    return <LoadingState label="Checking your Raahi session…" />
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  const activeCandidate: UnifiedCandidate | null = liveProfile ? normalizeFeedProfile(liveProfile) : null

  function showToast(message: string) {
    setFeedbackToast(message)
    window.setTimeout(() => setFeedbackToast(null), 2500)
  }

  async function handleAction(action: DiscoverAction) {
    if (!activeCandidate || busy || !liveProfile) return
    setBusy(true)

    const candidateToAct = activeCandidate
    const profileToAct = liveProfile
    const result = await recordAction(profileToAct, action)
    setBusy(false)
    if (!result) return

    const actionName = action === 'superlike' ? 'Super Liked ⭐' : action === 'like' ? 'Liked 💖' : 'Passed 👋'
    showToast(`${actionName} ${candidateToAct.name}`)

    if (action === 'superlike' || result.isMatch) {
      let resolvedChatId = result.chatId || candidateToAct.chatId
      if (!resolvedChatId) {
        try {
          const chats = await fetchChats()
          const found = chats.find(c => c.user.id === candidateToAct.id)
          if (found) resolvedChatId = found.chat_id
        } catch {
          // Keep null if chats cannot be reached
        }
      }

      setMatchedCandidate({
        ...candidateToAct,
        isSuperLike: action === 'superlike',
        chatId: resolvedChatId,
      })
    }
  }

  function handleRewind() {
    showToast('No recent pass to rewind.')
  }

  function handleResetFeed() {
    void refresh()
    showToast('Discover feed refreshed! ✨')
  }

  const theme = generationThemes[generation] || generationThemes.genz
  const candidatesRemaining = liveProfiles.length

  return (
    <PageContainer className="discover-page discover-live-page page-enter">
      {/* Toast Feedback Banner */}
      {feedbackToast && (
        <div className="discover-feedback-toast" role="status">
          {feedbackToast}
        </div>
      )}

      {/* Header */}
      <header className="discover-heading fiu">
        <div>
          <p className="integration-eyebrow">YOUR DISCOVER DECK</p>
          <h1>
            Meet your next <span>maybe.</span>
          </h1>
          <p className="discover-subtitle">
            A little spark, a real person. Follow your vibe without ghosting.
          </p>
        </div>
        <div className="discover-deck-meta">
          <span>
            <span className={`e ${theme.emojiAnimation}`} aria-hidden="true">
              {theme.emoji}
            </span>{' '}
            {theme.name} mode
          </span>
        </div>
      </header>

      {/* Discovery Stage */}
      {liveError && !liveLoading ? (
        <Card className="discover-empty card-enter">
          <div className="discover-empty-icon" aria-hidden="true">
            <span className="e e-float">⚠️</span>
          </div>
          <p className="integration-eyebrow">SOMETHING WENT WRONG</p>
          <h2>Could not load profiles</h2>
          <p>{liveError}</p>
          <div className="discover-detail-actions" style={{ justifyContent: 'center' }}>
            <button
              type="button"
              className="matches-primary-button"
              onClick={() => void refresh()}
            >
              Try again 🔄
            </button>
          </div>
        </Card>
      ) : liveLoading && !activeCandidate ? (
        <LoadingState label="Finding eligible profiles around you…" />
      ) : activeCandidate ? (
        <div className="discover-live-stage">
          <p className="discover-live-count">
            {candidatesRemaining} eligible connection{candidatesRemaining === 1 ? '' : 's'} in your deck
          </p>

          <ProfileCard
            key={activeCandidate.id}
            candidate={activeCandidate}
            onAction={handleAction}
            onOpenDetails={() => navigate(`/discover/${activeCandidate.id}`)}
            busy={busy}
          />

          {/* Swipe Hint */}
          <p className="discover-swipe-hint swipe-hint" aria-hidden="true">
            <span className="e e-swing">👈</span>
            <span>pass &nbsp;·&nbsp; like &nbsp;·&nbsp; super like 👆</span>
            <span className="e e-swing" style={{ animationDelay: '.4s' }}>👉</span>
          </p>

          {/* Interactive Action Buttons */}
          <div className="swipe-actions discover-actions">
            <button
              type="button"
              className="discover-action rewind"
              onClick={handleRewind}
              disabled={busy}
              title="Rewind last pass"
              aria-label="Rewind last pass"
            >
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
            </button>
            <button
              type="button"
              className="swipe-btn btn-pass-sw discover-action pass"
              onClick={() => void handleAction('pass')}
              disabled={busy}
              title="Pass"
              aria-label="Pass this profile"
            >
              <span className="e" aria-hidden="true">👋</span>
            </button>
            <button
              type="button"
              className="swipe-btn btn-super-sw discover-action super"
              onClick={() => void handleAction('superlike')}
              disabled={busy}
              title="Super Like"
              aria-label="Super like this profile"
            >
              <span className="e" aria-hidden="true">⭐</span>
            </button>
            <button
              type="button"
              className="swipe-btn btn-like-sw discover-action like"
              onClick={() => void handleAction('like')}
              disabled={busy}
              title="Like"
              aria-label="Like this profile"
            >
              <span className="e" aria-hidden="true">💖</span>
            </button>
          </div>
        </div>
      ) : (
        /* Empty Feed State */
        <Card className="discover-empty card-enter">
          <div className="discover-empty-icon" aria-hidden="true">
            <span className="e e-float">🌙</span>
          </div>
          <p className="integration-eyebrow">YOU’RE ALL CAUGHT UP</p>
          <h2>No more profiles right now.</h2>
          <p>
            You’ve seen everyone in your current circle! Catch up with your matches or refresh your feed anytime.
          </p>
          <div className="discover-detail-actions" style={{ justifyContent: 'center' }}>
            <button
              type="button"
              className="matches-primary-button"
              onClick={handleResetFeed}
            >
              Refresh Discover 🧭
            </button>
            <button
              type="button"
              className="matches-outline-button"
              onClick={() => navigate('/matches')}
            >
              View your matches 💬
            </button>
          </div>
        </Card>
      )}

      {/* MATCH / SUPER LIKE CELEBRATION MODAL */}
      {matchedCandidate && (
        <div
          className="discover-celebration-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={matchedCandidate.isSuperLike ? `Super Like sent to ${matchedCandidate.name}` : `Mutual match with ${matchedCandidate.name}`}
        >
          <div className="celebration-modal-card">
            <p className="celebration-eyebrow">
              {matchedCandidate.isSuperLike ? 'SUPER LIKE SENT! ⭐' : 'IT’S A MUTUAL MATCH!'}
            </p>
            <h2 className="celebration-title">
              {matchedCandidate.isSuperLike ? `You Super Liked ${matchedCandidate.name}!` : 'You two vibed! 🎉'}
            </h2>
            <p className="celebration-subtitle">
              {matchedCandidate.isSuperLike
                ? `You sent a Super Like to ${matchedCandidate.name}. You stand out in their deck!`
                : `You and ${matchedCandidate.name} both liked each other on Raahi.`}
            </p>

            <div className="celebration-clash" aria-hidden="true">
              <div
                className="celebration-avatar-ring"
                style={{ borderColor: 'var(--ep)', boxShadow: '0 0 24px rgba(216,61,180,0.5)', overflow: 'hidden' }}
              >
                <span>{user?.username ? user.username[0]?.toUpperCase() : '😎'}</span>
              </div>
              <span className="celebration-sparkle-center">
                {matchedCandidate.isSuperLike ? '⭐' : '💗'}
              </span>
              <div
                className="celebration-avatar-ring"
                style={{ borderColor: matchedCandidate.ringColor || 'var(--ep)', boxShadow: `0 0 24px ${matchedCandidate.ringColor || 'var(--ep)'}`, overflow: 'hidden' }}
              >
                <span>{matchedCandidate.initials || matchedCandidate.name[0]}</span>
              </div>
            </div>

            <div className="celebration-actions">
              <Link
                to={matchedCandidate.chatId ? `/conversations/${matchedCandidate.chatId}` : '/conversations'}
                className="celebration-chat-btn bpulse"
                onClick={() => setMatchedCandidate(null)}
              >
                Message 👋
              </Link>
              <button
                type="button"
                className="celebration-keep-btn"
                onClick={() => setMatchedCandidate(null)}
              >
                Keep Swiping
              </button>
            </div>
          </div>
        </div>
      )}

      {/* PROFILE DETAILS MODAL / DRAWER */}
      {detailsCandidate && (
        <div
          className="discover-profile-modal-overlay"
          onClick={() => setDetailsCandidate(null)}
          role="dialog"
          aria-modal="true"
          aria-label={`${detailsCandidate.name}'s profile details`}
        >
          <div
            className="discover-profile-modal-sheet"
            onClick={e => e.stopPropagation()}
          >
            <div className="modal-drag-handle" />
            <div style={{ position: 'absolute', top: 18, left: 18, zIndex: 10 }}>
              <SafetyMenuDropdown
                onOpenReport={() => setShowCandidateReport(true)}
                onOpenBlock={() => setShowCandidateBlock(true)}
                ariaLabel={`Safety options for ${detailsCandidate.name}`}
              />
            </div>
            <button
              type="button"
              className="modal-close-corner"
              onClick={() => setDetailsCandidate(null)}
              aria-label="Close profile details"
            >
              ✕
            </button>

            {/* Photo Gallery Row */}
            <div className="modal-photo-gallery">
              {detailsCandidate.photos.map((photo, i) => (
                <img
                  key={i}
                  src={resolveMediaUrl(photo)}
                  alt={`${detailsCandidate.name} view ${i + 1}`}
                  className="modal-gallery-img"
                  onError={e => {
                    const initial = detailsCandidate.name.trim()[0]?.toUpperCase() ?? 'R'
                    const ring = detailsCandidate.era === 'zillenial' ? '#f59e0b' : detailsCandidate.era === 'millennial' ? '#06b6d4' : '#a855f7'
                    e.currentTarget.src = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500" width="100%" height="100%"><rect width="100%" height="100%" fill="%23140a28"/><circle cx="200" cy="220" r="90" fill="${encodeURIComponent(ring)}" fill-opacity="0.25"/><circle cx="200" cy="220" r="75" fill="%231e0f38" stroke="${encodeURIComponent(ring)}" stroke-width="3"/><text x="200" y="250" font-family="sans-serif" font-size="70" font-weight="bold" fill="%23ffffff" text-anchor="middle">${initial}</text></svg>`
                  }}
                />
              ))}
            </div>

            <div className="modal-info-section">
              <h3 className="modal-candidate-name">
                {detailsCandidate.name}
                {detailsCandidate.age ? `, ${detailsCandidate.age}` : ''}
              </h3>
              <p className="modal-candidate-meta">
                {detailsCandidate.city} · {eraLabels[detailsCandidate.era] ?? detailsCandidate.era}
              </p>

              {(detailsCandidate.profession || detailsCandidate.education) && (
                <p className="modal-candidate-sub" style={{ fontSize: '.84rem', color: 'rgba(235,230,250,0.8)', margin: '4px 0 10px' }}>
                  {detailsCandidate.profession && <span>💼 {detailsCandidate.profession}</span>}
                  {detailsCandidate.profession && detailsCandidate.education && <span> · </span>}
                  {detailsCandidate.education && <span>🎓 {detailsCandidate.education}</span>}
                </p>
              )}

              {detailsCandidate.relationshipIntentions && (
                <div className="modal-intentions-chip" style={{ fontSize: '.8rem', color: '#f3e8ff', background: 'rgba(168,85,247,0.18)', border: '1px solid rgba(168,85,247,0.3)', borderRadius: 12, padding: '6px 12px', margin: '8px 0' }}>
                  <strong>Looking for:</strong> {detailsCandidate.relationshipIntentions}
                </div>
              )}

              {detailsCandidate.bio && (
                <>
                  <h4 className="modal-section-title">About</h4>
                  <p className="modal-bio-text">{detailsCandidate.bio}</p>
                </>
              )}

              {detailsCandidate.vibeTag && (
                <>
                  <h4 className="modal-section-title">Current Vibe</h4>
                  <div className="discover-tags">
                    <span>{detailsCandidate.vibeTag}</span>
                  </div>
                </>
              )}

              {detailsCandidate.tags && detailsCandidate.tags.length > 0 && (
                <>
                  <h4 className="modal-section-title">Passions & Lifestyle</h4>
                  <div className="discover-tags">
                    {detailsCandidate.tags.map((t, i) => (
                      <span key={i}>{t}</span>
                    ))}
                  </div>
                </>
              )}

              {detailsCandidate.compatibilityScore != null && (
                <div className="discover-alignment" style={{ marginTop: 18 }}>
                  <strong>{detailsCandidate.compatibilityScore}%</strong>
                  <span>Compatibility alignment with your generation vibe</span>
                </div>
              )}
            </div>

            <div className="modal-action-bar">
              <button
                type="button"
                className="swipe-btn btn-pass-sw discover-action pass"
                onClick={() => {
                  setDetailsCandidate(null)
                  void handleAction('pass')
                }}
                aria-label="Pass"
              >
                👋
              </button>
              <button
                type="button"
                className="swipe-btn btn-super-sw discover-action super"
                onClick={() => {
                  setDetailsCandidate(null)
                  void handleAction('superlike')
                }}
                aria-label="Super Like"
              >
                ⭐
              </button>
              <button
                type="button"
                className="swipe-btn btn-like-sw discover-action like"
                onClick={() => {
                  setDetailsCandidate(null)
                  void handleAction('like')
                }}
                aria-label="Like"
              >
                💖
              </button>
            </div>
          </div>

          <BlockConfirmationModal
            isOpen={showCandidateBlock}
            targetUserId={detailsCandidate.id}
            targetName={detailsCandidate.name}
            isMatchOrChat={false}
            onClose={() => setShowCandidateBlock(false)}
            onSuccess={() => {
              const blockedId = detailsCandidate.id
              const blockedName = detailsCandidate.name
              setDetailsCandidate(null)
              window.dispatchEvent(new CustomEvent('raahi:user-blocked', { detail: { userId: blockedId } }))
              showToast(`Blocked ${blockedName}. Removed from Discover.`)
            }}
          />
          <ReportUserModal
            isOpen={showCandidateReport}
            targetUserId={detailsCandidate.id}
            targetName={detailsCandidate.name}
            onClose={() => setShowCandidateReport(false)}
            onSuccess={(msg) => {
              showToast(msg)
            }}
          />
        </div>
      )}
    </PageContainer>
  )
}

export function DiscoverProfilePage() {
  const { profileId } = useParams()
  const { user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const [profile, setProfile] = useState<PublicProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activePhotoIndex, setActivePhotoIndex] = useState(0)
  const [showProfileBlock, setShowProfileBlock] = useState(false)
  const [showProfileReport, setShowProfileReport] = useState(false)

  useEffect(() => {
    let active = true

    if (!profileId || !/^\d+$/.test(profileId)) {
      setError('Profile not found.')
      setLoading(false)
      return
    }

    void fetchPublicProfile(Number(profileId))
      .then(value => {
        if (active) setProfile(value)
      })
      .catch(cause => {
        if (active) {
          setError(
            cause instanceof ApiError && cause.status === 404
              ? 'This profile is no longer available.'
              : cause instanceof Error
                ? cause.message
                : 'Could not load this profile.'
          )
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [profileId])

  if (authLoading) return <LoadingState label="Checking your Raahi session…" />
  if (!user) return <Navigate to="/login" replace />
  if (loading) return <LoadingState label="Loading profile details…" />

  if (error || !profile) {
    return (
      <PageContainer className="discover-page">
        <Card className="discover-empty">
          <h1>Profile unavailable</h1>
          <p>{error || 'This profile could not be found.'}</p>
          <Link className="discover-details-link" to="/discover">
            Back to Discover
          </Link>
        </Card>
      </PageContainer>
    )
  }

  const name = profile.full_name || profile.username || 'Raahi member'
  const initial = name.trim()[0]?.toUpperCase() ?? 'R'
  const eraKey = profile.era || 'genz'
  const photos = profile.photos && profile.photos.length > 0
    ? profile.photos
    : (profile.photo_url ? [profile.photo_url] : [])
  const currentPhoto = photos.length > 0 ? resolveMediaUrl(photos[activePhotoIndex] || photos[0]) : null

  return (
    <PageContainer className="discover-page page-enter">
      <div className="discover-detail-container">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <Link className="discover-back-link" to="/discover" style={{ marginTop: 0 }}>
            ← Back to Discover
          </Link>
          <SafetyMenuDropdown
            onOpenReport={() => setShowProfileReport(true)}
            onOpenBlock={() => setShowProfileBlock(true)}
            ariaLabel={`Safety options for ${name}`}
          />
        </div>
        <div className="discover-detail-grid">
          {/* Left Column: Photos or Avatar Artwork */}
          <div className="discover-detail-gallery">
            {currentPhoto ? (
              <div className="discover-detail-main-img-wrap">
                <img
                  src={currentPhoto}
                  alt={`${name} photo ${activePhotoIndex + 1}`}
                  className="discover-detail-main-img"
                  onError={e => {
                    const ring = eraKey === 'zillenial' ? '#f59e0b' : eraKey === 'millennial' ? '#06b6d4' : '#a855f7'
                    e.currentTarget.src = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500" width="100%" height="100%"><rect width="100%" height="100%" fill="%23140a28"/><circle cx="200" cy="220" r="90" fill="${encodeURIComponent(ring)}" fill-opacity="0.25"/><circle cx="200" cy="220" r="75" fill="%231e0f38" stroke="${encodeURIComponent(ring)}" stroke-width="3"/><text x="200" y="250" font-family="sans-serif" font-size="70" font-weight="bold" fill="%23ffffff" text-anchor="middle">${initial}</text></svg>`
                  }}
                />
                <span className="discover-detail-corner-badge">
                  {eraLabels[eraKey] ?? eraKey} · {profile.city}
                </span>
              </div>
            ) : (
              <div className={`discover-artwork era-${eraKey}`} style={{ minHeight: 380, borderRadius: 24 }}>
                <div className="discover-artwork-orbit" />
                <div className="discover-avatar e-float">
                  <span>{initial}</span>
                </div>
                <span className="discover-artwork-note">
                  {(profile as any).is_verified || ((profile as any).is_face_verified && (profile as any).is_id_verified)
                    ? '✦ Verified Raahi Member'
                    : '✦ Raahi Member'}
                </span>
              </div>
            )}

            {photos.length > 1 && (
              <div className="discover-detail-thumb-row" aria-label="Photo gallery thumbnails">
                {photos.map((photo, i) => (
                  <button
                    key={i}
                    type="button"
                    className={`discover-detail-thumb-btn${i === activePhotoIndex ? ' active' : ''}`}
                    onClick={() => setActivePhotoIndex(i)}
                    aria-label={`View photo ${i + 1}`}
                  >
                    <img src={resolveMediaUrl(photo)} alt={`${name} thumbnail ${i + 1}`} />
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Right Column: Live Profile Info */}
          <Card className="discover-detail-copy card-enter">
            <p className="integration-eyebrow">PROFILE DETAILS</p>
            <h1>
              {name}
              {profile.age ? `, ${profile.age}` : ''}
            </h1>
            <p className="discover-detail-meta">
              {profile.city} · {eraLabels[profile.era] ?? profile.era}
            </p>
            {(profile.profession || profile.education) && (
              <p className="discover-detail-profession" style={{ fontSize: '.88rem', color: 'rgba(235,230,250,0.85)', margin: '4px 0 12px' }}>
                {profile.profession && <span>💼 {profile.profession}</span>}
                {profile.profession && profile.education && <span> · </span>}
                {profile.education && <span>🎓 {profile.education}</span>}
              </p>
            )}
            {profile.relationship_intentions && (
              <div className="discover-detail-intentions" style={{ fontSize: '.82rem', color: '#f3e8ff', background: 'rgba(168,85,247,0.18)', border: '1px solid rgba(168,85,247,0.35)', borderRadius: 12, padding: '8px 14px', margin: '10px 0 14px', display: 'inline-block' }}>
                <strong>Looking for:</strong> {profile.relationship_intentions}
              </div>
            )}
            {profile.bio && <p style={{ lineHeight: 1.6, margin: '10px 0' }}>{profile.bio}</p>}
            {profile.interests && profile.interests.length > 0 && (
              <>
                <h2>Passions & Lifestyle</h2>
                <div className="discover-tags" style={{ margin: '8px 0 16px' }}>
                  {profile.interests.map((t, idx) => (
                    <span key={idx}>{t}</span>
                  ))}
                </div>
              </>
            )}
            {profile.vibe_tag && (
              <>
                <h2>Current vibe</h2>
                <div className="discover-tags">
                  <span>{profile.vibe_tag}</span>
                </div>
              </>
            )}
            <div className="discover-detail-actions">
              <button
                type="button"
                className="matches-outline-button"
                onClick={() => navigate('/discover')}
              >
                Back to Discover
              </button>
            </div>
          </Card>
        </div>
      </div>

      <BlockConfirmationModal
        isOpen={showProfileBlock}
        targetUserId={Number(profileId)}
        targetName={name}
        isMatchOrChat={false}
        onClose={() => setShowProfileBlock(false)}
        onSuccess={() => {
          window.dispatchEvent(new CustomEvent('raahi:user-blocked', { detail: { userId: Number(profileId) } }))
          navigate('/discover')
        }}
      />
      <ReportUserModal
        isOpen={showProfileReport}
        targetUserId={Number(profileId)}
        targetName={name}
        onClose={() => setShowProfileReport(false)}
        onSuccess={() => {
          navigate('/discover')
        }}
      />
    </PageContainer>
  )
}

export function DemoMatchPage() {
  return <Navigate to="/matches" replace />
}

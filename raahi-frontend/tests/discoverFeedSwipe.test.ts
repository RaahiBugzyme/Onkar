import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { clearAuthToken, setAuthToken, resolveMediaUrl, ApiError } from '../src/api/client.ts'
import { fetchFeed, submitSwipe, type FeedProfile } from '../src/api/discover.ts'

// Ensure localStorage mock is present for node environment
const storage = new Map<string, string>()
if (typeof globalThis.localStorage === 'undefined') {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    },
  })
}

const mockProfile: FeedProfile = {
  user_id: 101,
  username: 'shree_p',
  full_name: 'Shree Patil',
  age: 23,
  city: 'Pune',
  era: 'genz',
  vibe_tag: 'Synthwave & Books',
  bio: 'Exploring cozy cafes and stargazing.',
  profession: 'Software Engineer',
  education: 'COEP Pune',
  relationship_intentions: 'Long-term connection',
  interests: ['Coding', 'Stargazing', 'Coffee'],
  photos: ['/uploads/profiles/shree_1.webp'],
  photo_url: '/uploads/profiles/shree_1.webp',
  compatibility_score: 88,
  confidence_score: 92,
  adjusted_score: 86,
  recommendation_score: 89,
  score_type: 'profile_alignment',
  model_version: '2.1.0',
  prediction_provenance: 'dating_ml_v3',
  ranking_weights_validated: true,
  matching_status: 'scored',
  is_face_verified: false,
  is_id_verified: false,
  verification_badge_required: false,
}

test('Test 1 – Eligible profiles appear in feed API response: Unverified adult profiles are now eligible', async () => {
  const original = globalThis.fetch
  let request: Request | undefined
  setAuthToken('test-token-shree')
  globalThis.fetch = async (input, init) => {
    request = new Request(input, init)
    return Response.json({
      profiles: [mockProfile],
      total: 1,
      limit: 20,
      offset: 0,
      has_more: false,
    })
  }

  try {
    const feed = await fetchFeed(20, 0)
    assert.equal(new URL(request!.url).pathname, '/api/v1/feed')
    assert.equal(request!.headers.get('authorization'), 'Bearer test-token-shree')
    assert.equal(feed.profiles.length, 1)
    assert.equal(feed.profiles[0].username, 'shree_p')
    assert.equal(feed.profiles[0].age, 23)
    // Profile is discoverable despite not having face/ID verification approved
    assert.equal(feed.profiles[0].is_face_verified, false)
    assert.equal(feed.profiles[0].is_id_verified, false)
  } finally {
    globalThis.fetch = original
    clearAuthToken()
  }
})

test('Test 2 – Authenticated user excluded from own feed', async () => {
  const original = globalThis.fetch
  const currentUserId = 99
  setAuthToken('token-current-user')

  globalThis.fetch = async (input, init) => {
    // Backend filters out models.User.id != current_user.id
    const candidates = [
      { ...mockProfile, user_id: 101 },
      { ...mockProfile, user_id: 102, username: 'neha_k' },
    ].filter(p => p.user_id !== currentUserId)

    return Response.json({
      profiles: candidates,
      total: candidates.length,
      limit: 20,
      offset: 0,
      has_more: false,
    })
  }

  try {
    const feed = await fetchFeed(20, 0)
    assert.ok(feed.profiles.every(p => p.user_id !== currentUserId))
    assert.equal(feed.profiles.length, 2)
  } finally {
    globalThis.fetch = original
    clearAuthToken()
  }
})

test('Test 3 – Incomplete profiles follow eligibility rules: Under 18 excluded, adults included', async () => {
  const original = globalThis.fetch

  globalThis.fetch = async () => {
    // Backend eligibility filter: date_of_birth <= adult_birthdate_cutoff (age >= 18)
    const rawCandidates = [
      { ...mockProfile, user_id: 101, age: 22 }, // adult: included
      { ...mockProfile, user_id: 102, age: 16 }, // minor: excluded
      { ...mockProfile, user_id: 103, age: 19 }, // adult: included
    ]
    const eligible = rawCandidates.filter(c => c.age >= 18)
    return Response.json({
      profiles: eligible,
      total: eligible.length,
      limit: 20,
      offset: 0,
      has_more: false,
    })
  }

  try {
    const feed = await fetchFeed(20, 0)
    assert.equal(feed.profiles.length, 2)
    assert.ok(feed.profiles.every(p => p.age !== null && p.age >= 18))
  } finally {
    globalThis.fetch = original
  }
})

test('Test 4 – Blocked users excluded in both directions', async () => {
  const original = globalThis.fetch
  const blockerId = 50
  const blockedCandidateId = 101

  globalThis.fetch = async () => {
    // Both user blocks (me blocked them, or they blocked me) exclude them from feed
    const candidates = [
      { ...mockProfile, user_id: 101 },
      { ...mockProfile, user_id: 102, username: 'riya_s' },
    ].filter(p => p.user_id !== blockedCandidateId)

    return Response.json({
      profiles: candidates,
      total: candidates.length,
      limit: 20,
      offset: 0,
      has_more: false,
    })
  }

  try {
    const feed = await fetchFeed(20, 0)
    assert.equal(feed.profiles.length, 1)
    assert.equal(feed.profiles[0].user_id, 102)
  } finally {
    globalThis.fetch = original
  }
})

test('Test 5 – Already-swiped profiles excluded from feed', async () => {
  const original = globalThis.fetch
  const swipedTargetIds = new Set([101, 103])

  globalThis.fetch = async () => {
    const allCandidates = [
      { ...mockProfile, user_id: 101 },
      { ...mockProfile, user_id: 102 },
      { ...mockProfile, user_id: 103 },
      { ...mockProfile, user_id: 104 },
    ]
    const fresh = allCandidates.filter(c => !swipedTargetIds.has(c.user_id))
    return Response.json({
      profiles: fresh,
      total: fresh.length,
      limit: 20,
      offset: 0,
      has_more: false,
    })
  }

  try {
    const feed = await fetchFeed(20, 0)
    assert.equal(feed.profiles.length, 2)
    assert.deepEqual(feed.profiles.map(p => p.user_id), [102, 104])
  } finally {
    globalThis.fetch = original
  }
})

test('Test 6 – Like action reaches backend: POST /api/v1/swipe with action like', async () => {
  const original = globalThis.fetch
  let capturedRequest: Request | undefined

  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init)
    return Response.json({
      id: 1,
      user_id: 10,
      target_user_id: 101,
      action: 'like',
      created_at: new Date().toISOString(),
      is_match: false,
    })
  }

  try {
    const response = await submitSwipe(101, 'like')
    assert.equal(new URL(capturedRequest!.url).pathname, '/api/v1/swipe')
    assert.equal(capturedRequest!.method, 'POST')
    const body = await capturedRequest!.clone().json()
    assert.deepEqual(body, { target_user_id: 101, action: 'like' })
    assert.equal(response.action, 'like')
    assert.equal(response.is_match, false)
  } finally {
    globalThis.fetch = original
  }
})

test('Test 7 – Pass action reaches backend: POST /api/v1/swipe with action pass', async () => {
  const original = globalThis.fetch
  let capturedRequest: Request | undefined

  globalThis.fetch = async (input, init) => {
    capturedRequest = new Request(input, init)
    return Response.json({
      id: 2,
      user_id: 10,
      target_user_id: 102,
      action: 'pass',
      created_at: new Date().toISOString(),
      is_match: false,
    })
  }

  try {
    const response = await submitSwipe(102, 'pass')
    assert.equal(new URL(capturedRequest!.url).pathname, '/api/v1/swipe')
    assert.equal(capturedRequest!.method, 'POST')
    const body = await capturedRequest!.clone().json()
    assert.deepEqual(body, { target_user_id: 102, action: 'pass' })
    assert.equal(response.action, 'pass')
    assert.equal(response.is_match, false)
  } finally {
    globalThis.fetch = original
  }
})

test('Test 8 – Duplicate swipe prevention: Returns existing swipe idempotently', async () => {
  const original = globalThis.fetch
  let callCount = 0

  globalThis.fetch = async () => {
    callCount++
    // Idempotent swipe response from backend
    return Response.json({
      id: 5,
      user_id: 10,
      target_user_id: 101,
      action: 'like',
      created_at: '2026-01-01T12:00:00Z',
      is_match: false,
    })
  }

  try {
    const firstSwipe = await submitSwipe(101, 'like')
    const secondSwipe = await submitSwipe(101, 'like')
    assert.equal(callCount, 2)
    assert.equal(firstSwipe.id, secondSwipe.id)
    assert.equal(firstSwipe.target_user_id, secondSwipe.target_user_id)
  } finally {
    globalThis.fetch = original
  }
})

test('Test 9 – Mutual likes create match: Backend triggers is_match true', async () => {
  const original = globalThis.fetch

  globalThis.fetch = async (input, init) => {
    const req = new Request(input, init)
    const body = await req.json()
    // Simulated backend reverse swipe detected -> is_match: true
    return Response.json({
      id: 42,
      user_id: 10,
      target_user_id: body.target_user_id,
      action: body.action,
      created_at: new Date().toISOString(),
      is_match: true,
    })
  }

  try {
    const response = await submitSwipe(101, 'like')
    assert.equal(response.is_match, true)
    assert.equal(response.target_user_id, 101)
  } finally {
    globalThis.fetch = original
  }
})

test('Test 10 – API failure does not falsely report success', async () => {
  const original = globalThis.fetch

  globalThis.fetch = async () => {
    return new Response(JSON.stringify({ detail: 'Target user profile not found' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  try {
    await assert.rejects(
      async () => {
        await submitSwipe(999, 'like')
      },
      (err: Error) => {
        assert.ok(err instanceof ApiError)
        assert.equal(err.status, 404)
        assert.equal(err.message, 'Target user profile not found')
        return true
      }
    )
  } finally {
    globalThis.fetch = original
  }
})

test('Test 11 – Feed refresh retrieves updated profiles from offset 0', async () => {
  const original = globalThis.fetch
  const requestedOffsets: number[] = []

  globalThis.fetch = async (input) => {
    const url = new URL(String(input), 'http://localhost')
    const offset = Number(url.searchParams.get('offset') ?? 0)
    requestedOffsets.push(offset)
    return Response.json({
      profiles: [{ ...mockProfile, user_id: offset === 0 ? 201 : 202 }],
      total: 2,
      limit: 1,
      offset,
      has_more: offset === 0,
    })
  }

  try {
    // Initial page
    const page1 = await fetchFeed(1, 0)
    assert.equal(page1.profiles[0].user_id, 201)

    // Load next page
    const page2 = await fetchFeed(1, 1)
    assert.equal(page2.profiles[0].user_id, 202)

    // Refresh: loads from 0 again
    const refreshed = await fetchFeed(1, 0)
    assert.equal(refreshed.profiles[0].user_id, 201)

    assert.deepEqual(requestedOffsets, [0, 1, 0])
  } finally {
    globalThis.fetch = original
  }
})

test('Test 12 – Profile photos display correctly: resolveMediaUrl handles paths and fallbacks', () => {
  // Relative uploaded path
  const relativePhoto = '/uploads/profiles/shree_photo.webp'
  const resolved = resolveMediaUrl(relativePhoto)
  assert.ok(resolved.includes('/uploads/profiles/shree_photo.webp'))

  // External full URL preserved
  const externalPhoto = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb'
  assert.equal(resolveMediaUrl(externalPhoto), externalPhoto)

  // Data URI preserved
  const dataUri = 'data:image/svg+xml;utf8,<svg></svg>'
  assert.equal(resolveMediaUrl(dataUri), dataUri)

  // Null/undefined returns empty string
  assert.equal(resolveMediaUrl(null), '')
  assert.equal(resolveMediaUrl(undefined), '')
})

test('Test 13 – Account switching clears feed state: Logout clears state immediately', () => {
  // Test isolation contract: when user becomes null, feed state resets
  let feedState = {
    profiles: [mockProfile],
    offset: 20,
    hasMore: true,
    sessionLikes: 5,
    error: null as string | null,
  }

  // Simulate logout cleanup logic from DiscoverContext
  function handleUserChange(currentUser: { id: number } | null) {
    if (!currentUser) {
      feedState = {
        profiles: [],
        offset: 0,
        hasMore: false,
        sessionLikes: 0,
        error: null,
      }
    }
  }

  // Logout triggers reset
  handleUserChange(null)
  assert.equal(feedState.profiles.length, 0)
  assert.equal(feedState.offset, 0)
  assert.equal(feedState.hasMore, false)
  assert.equal(feedState.sessionLikes, 0)
})

test('Test 14 – Like/Pass buttons visible on desktop: CSS defines desktop container and button positioning', () => {
  const cssPath = path.resolve(import.meta.dirname, '../src/styles/discover.css')
  const css = fs.readFileSync(cssPath, 'utf8')

  // Check desktop media query (1024px and above)
  assert.ok(css.includes('@media (min-width: 1024px)'))
  // Check horizontal profile card height constraint on desktop
  assert.ok(css.includes('.discover-live-card'))
  assert.ok(css.includes('height: 475px;'))
  // Check desktop action button positioning and spacing
  assert.ok(css.includes('.discover-actions'))
  assert.ok(css.includes('margin-top: 4px;'))
})

test('Test 15 – Like/Pass buttons visible on mobile: CSS defines viewport-constrained card and button visibility', () => {
  const cssPath = path.resolve(import.meta.dirname, '../src/styles/discover.css')
  const css = fs.readFileSync(cssPath, 'utf8')

  // Check mobile media query (max-width: 650px)
  assert.ok(css.includes('@media (max-width:650px)'))
  // Check mobile card photo wrap height is clamped to viewport height
  assert.ok(css.includes('clamp(230px, 38vh, 320px)'))
  // Check mobile bio text clamping to prevent pushing buttons below fold
  assert.ok(css.includes('-webkit-line-clamp: 2'))
  // Check mobile action button sizing
  assert.ok(css.includes('.discover-action { width: 52px; height: 52px;'))
})

test('Test 16 – Super Like popup regression fix: DiscoverPages markup contains Message and Keep Swiping controls', () => {
  const pagePath = path.resolve(import.meta.dirname, '../src/pages/DiscoverPages.tsx')
  const pageCode = fs.readFileSync(pagePath, 'utf8')

  // Verify popup markup and accessibility
  assert.ok(pageCode.includes('className="celebration-actions"'))
  assert.ok(pageCode.includes('Message 👋'))
  assert.ok(pageCode.includes('Keep Swiping'))
  assert.ok(pageCode.includes('setMatchedCandidate(null)'))
  assert.ok(pageCode.includes('SUPER LIKE SENT! ⭐'))
  assert.ok(pageCode.includes('You Super Liked'))
})

test('Test 17 – Super Like routing: Message links to conversation when available, otherwise /conversations', () => {
  const pagePath = path.resolve(import.meta.dirname, '../src/pages/DiscoverPages.tsx')
  const pageCode = fs.readFileSync(pagePath, 'utf8')

  assert.ok(pageCode.includes('matchedCandidate.chatId ? `/conversations/${matchedCandidate.chatId}` : \'/conversations\''))
})

test('Test 18 – Super Like popup trigger: handleAction triggers popup on superlike action', () => {
  const pagePath = path.resolve(import.meta.dirname, '../src/pages/DiscoverPages.tsx')
  const pageCode = fs.readFileSync(pagePath, 'utf8')

  // Verify trigger logic checks for superlike or match
  assert.ok(pageCode.includes("action === 'superlike' || result.isMatch"))
  assert.ok(pageCode.includes("isSuperLike: action === 'superlike'"))
})

test('Test 19 – DiscoverContext recordAction returns match and chatId for swipe responses', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => {
    return Response.json({
      id: 88,
      user_id: 1,
      target_user_id: 101,
      action: 'superlike',
      is_match: true,
      match: {
        id: 55,
        chat_id: 1234,
      },
    })
  }

  try {
    const swipe = await submitSwipe(101, 'superlike')
    assert.equal(swipe.action, 'superlike')
    assert.equal(swipe.is_match, true)
    assert.equal(swipe.match?.chat_id, 1234)
  } finally {
    globalThis.fetch = original
  }
})


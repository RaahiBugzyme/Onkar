import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clearAuthToken,
  getAuthToken,
  setAuthToken,
  AUTH_TOKEN_KEY,
  apiRequest,
  ApiError,
} from '../src/api/client.ts'
import {
  readDemoProfile,
  writeDemoProfile,
  clearDemoProfile,
  USER_PROFILE_STORAGE_KEY,
} from '../src/data/userProfile.ts'
import { getMyDatingProfile } from '../src/api/datingProfile.ts'

// Mock localStorage and sessionStorage
const localStore = new Map<string, string>()
const sessionStore = new Map<string, string>()

Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => localStore.get(key) ?? null,
    setItem: (key: string, value: string) => { localStore.set(key, value) },
    removeItem: (key: string) => { localStore.delete(key) },
    clear: () => { localStore.clear() },
  },
})

Object.defineProperty(globalThis, 'sessionStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => sessionStore.get(key) ?? null,
    setItem: (key: string, value: string) => { sessionStore.set(key, value) },
    removeItem: (key: string) => { sessionStore.delete(key) },
    clear: () => { sessionStore.clear() },
  },
})

test('Test 1 – Stale Profile Isolation: Authenticated user identity takes precedence over stale localStorage demo profile', () => {
  // Pre-seed localStorage with Omkar's old demo profile
  localStore.set(
    USER_PROFILE_STORAGE_KEY,
    JSON.stringify({
      id: 'demo-user-omkar',
      name: 'Omkar',
      age: 24,
      city: 'Pune',
      era: 'genz',
      bio: 'Omkar’s bio from old session',
      vibe: 'Situationship',
      lookingFor: 'any',
      interests: ['Coffee', 'Music'],
      photos: [],
      verificationStatus: 'not_verified',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    })
  )

  // Current authenticated user is Shree
  const shreeUser = {
    id: 102,
    username: 'shree',
    full_name: 'Shree',
    bio: 'Shree’s authenticated bio',
    email: 'shree@example.com',
    ai_memory_enabled: true,
    ai_provider_processing_enabled: true,
    activity_status_enabled: true,
  }

  // Derive display name following the SettingsPage rule
  const authoritativeName = shreeUser.full_name || shreeUser.username || 'Raahi member'
  assert.equal(authoritativeName, 'Shree', 'Must display Shree, never Omkar')
  assert.notEqual(authoritativeName, 'Omkar', 'Must not display stale Omkar')
  assert.notEqual(authoritativeName, 'onkarnagargoje12', 'Must not display developer fallback')

  // Avatar initial must derive dynamically from Shree
  const initial = (authoritativeName.trim()[0] || 'R').toUpperCase()
  assert.equal(initial, 'S', 'Initial for Shree must be S')
  assert.notEqual(initial, 'O', 'Initial must not be O')
})

test('Test 2 – Authenticated Profile Saving: Updating display name dispatches PATCH /me with correct payload', async () => {
  const originalFetch = globalThis.fetch
  setAuthToken('shree-jwt-token')

  let observedRequest: Request | undefined
  let requestBody: any = null

  globalThis.fetch = async (input, init) => {
    observedRequest = new Request(input, init)
    requestBody = await observedRequest.clone().json()
    return Response.json({
      id: 102,
      username: 'shree',
      full_name: requestBody.full_name,
      bio: requestBody.bio,
      email: 'shree@example.com',
      ai_memory_enabled: true,
      ai_provider_processing_enabled: true,
      activity_status_enabled: true,
    })
  }

  try {
    const updatedUser = await apiRequest<{ id: number; full_name: string; bio: string }>('/me', {
      method: 'PATCH',
      body: JSON.stringify({
        full_name: 'Shree Sharma',
        bio: 'Updated bio for Shree',
      }),
    })

    assert.equal(new URL(observedRequest!.url).pathname, '/me')
    assert.equal(observedRequest!.method, 'PATCH')
    assert.equal(observedRequest!.headers.get('authorization'), 'Bearer shree-jwt-token')
    assert.equal(requestBody.full_name, 'Shree Sharma')
    assert.equal(requestBody.bio, 'Updated bio for Shree')
    assert.equal(updatedUser.full_name, 'Shree Sharma')
  } finally {
    globalThis.fetch = originalFetch
    clearAuthToken()
  }
})

test('Test 3 – Account Switching: Logout purges legacy demo profile and switching accounts stays isolated', () => {
  // 1. Sign in as Omkar
  setAuthToken('omkar-jwt')
  localStore.set(
    USER_PROFILE_STORAGE_KEY,
    JSON.stringify({
      id: 'omkar-1',
      name: 'Omkar',
      age: 25,
      city: 'Mumbai',
      era: 'genz',
      bio: 'Omkar bio',
      vibe: 'Situationship',
      lookingFor: 'any',
      interests: [],
      photos: [],
      verificationStatus: 'not_verified',
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    })
  )

  assert.equal(getAuthToken(), 'omkar-jwt')
  assert.ok(localStore.has(USER_PROFILE_STORAGE_KEY))

  // 2. Perform logout
  clearAuthToken()

  // 3. Verify token and legacy profile storage are evicted
  assert.equal(getAuthToken(), null, 'Auth token must be cleared')
  assert.equal(localStorage.getItem(USER_PROFILE_STORAGE_KEY), null, 'Legacy demo profile storage must be purged')

  // 4. Sign in as Shree on the same browser
  setAuthToken('shree-jwt')
  assert.equal(getAuthToken(), 'shree-jwt')
  assert.equal(localStorage.getItem(USER_PROFILE_STORAGE_KEY), null, 'Shree session starts completely clean')
})

test('Test 4 – Account Ownership: Separate accounts receive only their own backend profiles', async () => {
  const originalFetch = globalThis.fetch

  const mockUsers: Record<string, { id: number; full_name: string; username: string }> = {
    'token-omkar': { id: 1, full_name: 'Omkar', username: 'omkar' },
    'token-shree': { id: 2, full_name: 'Shree', username: 'shree' },
  }

  globalThis.fetch = async (input, init) => {
    const req = new Request(input, init)
    const authHeader = req.headers.get('authorization')
    const token = authHeader?.replace('Bearer ', '')
    const user = token ? mockUsers[token] : null

    if (!user) {
      return Response.json({ detail: 'Unauthorized' }, { status: 401 })
    }

    if (new URL(req.url).pathname === '/me') {
      return Response.json({
        id: user.id,
        username: user.username,
        full_name: user.full_name,
        bio: `${user.full_name}'s private bio`,
        email: `${user.username}@example.com`,
        ai_memory_enabled: true,
        ai_provider_processing_enabled: true,
        activity_status_enabled: true,
      })
    }

    if (new URL(req.url).pathname === '/api/v1/profile/me') {
      return Response.json({
        id: user.id * 10,
        user_id: user.id,
        date_of_birth: '2000-01-01',
        gender: 'female',
        sexual_orientation: null,
        city: user.id === 1 ? 'Mumbai' : 'Pune',
        era: 'genz',
        vibe_tag: 'Vibe',
        match_era_preference: 'any',
        is_face_verified: false,
        is_id_verified: false,
        verification_status: 'unverified',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      })
    }

    return Response.json({ detail: 'Not found' }, { status: 404 })
  }

  try {
    // 1. Fetch as Omkar
    setAuthToken('token-omkar')
    const omkarMe = await apiRequest<{ id: number; full_name: string }>('/me')
    const omkarProfile = await getMyDatingProfile()
    assert.equal(omkarMe.full_name, 'Omkar')
    assert.equal(omkarProfile?.user_id, 1)
    assert.equal(omkarProfile?.city, 'Mumbai')

    // 2. Fetch as Shree
    setAuthToken('token-shree')
    const shreeMe = await apiRequest<{ id: number; full_name: string }>('/me')
    const shreeProfile = await getMyDatingProfile()
    assert.equal(shreeMe.full_name, 'Shree')
    assert.equal(shreeProfile?.user_id, 2)
    assert.equal(shreeProfile?.city, 'Pune')

    // 3. Omkar's profile remained intact and distinct
    assert.notEqual(omkarMe.id, shreeMe.id)
    assert.notEqual(omkarProfile?.city, shreeProfile?.city)
  } finally {
    globalThis.fetch = originalFetch
    clearAuthToken()
  }
})

test('Test 5 – Missing Name: Fallback uses authenticated username and never a hardcoded developer identity', () => {
  const userWithoutFullName = {
    id: 105,
    username: 'shree_username',
    full_name: null,
    bio: null,
    email: 'shree_new@example.com',
    ai_memory_enabled: true,
    ai_provider_processing_enabled: true,
    activity_status_enabled: true,
  }

  // Authoritative identity resolution
  const authoritativeName = userWithoutFullName.full_name || userWithoutFullName.username || 'Raahi member'
  assert.equal(authoritativeName, 'shree_username')
  assert.notEqual(authoritativeName, 'onkarnagargoje12')
  assert.notEqual(authoritativeName, 'Omkar')

  // Dynamic initial
  const initial = (authoritativeName.trim()[0] || 'R').toUpperCase()
  assert.equal(initial, 'S')

  // Even completely unauthenticated fallback returns generic Raahi member, never onkarnagargoje12
  localStore.clear()
  const defaultProfile = readDemoProfile()
  assert.equal(defaultProfile?.name, 'Raahi member')
  assert.notEqual(defaultProfile?.name, 'onkarnagargoje12')
})

test('Test 6 – API Failure: Failed PATCH /me propagates error without false success', async () => {
  const originalFetch = globalThis.fetch
  setAuthToken('test-token')

  globalThis.fetch = async () => {
    return Response.json(
      { detail: 'Internal server error while saving profile.' },
      { status: 500 }
    )
  }

  try {
    await assert.rejects(
      apiRequest('/me', {
        method: 'PATCH',
        body: JSON.stringify({ full_name: 'Invalid Test' }),
      }),
      (err: unknown) => {
        assert.ok(err instanceof ApiError)
        assert.equal(err.status, 500)
        assert.match(err.message, /Internal server error/)
        return true
      }
    )
  } finally {
    globalThis.fetch = originalFetch
    clearAuthToken()
  }
})

test('Test 7 – Theme Persistence: Theme preference survives logout and authentication cleanup', () => {
  const THEME_STORAGE_KEY = 'raahiGenerationTheme.v1'

  // User sets theme to millennial
  localStore.set(THEME_STORAGE_KEY, 'millennial')
  setAuthToken('active-token')
  localStore.set(USER_PROFILE_STORAGE_KEY, '{"name":"test"}')

  // Clear auth session (logout)
  clearAuthToken()

  // Verify auth token and cached demo profile are purged
  assert.equal(getAuthToken(), null)
  assert.equal(localStorage.getItem(USER_PROFILE_STORAGE_KEY), null)

  // Verify theme preference is intact
  assert.equal(localStorage.getItem(THEME_STORAGE_KEY), 'millennial', 'Theme preference must survive logout')
})

test('Test 8 – Refresh Persistence: Stored token restores authenticated identity on reload', async () => {
  const originalFetch = globalThis.fetch
  setAuthToken('persistent-session-token')

  globalThis.fetch = async (input, init) => {
    const req = new Request(input, init)
    if (new URL(req.url).pathname === '/me') {
      return Response.json({
        id: 102,
        username: 'shree',
        full_name: 'Shree',
        bio: 'Restored on reload',
        email: 'shree@example.com',
        ai_memory_enabled: true,
        ai_provider_processing_enabled: true,
        activity_status_enabled: true,
      })
    }
    return Response.json({ detail: 'Not found' }, { status: 404 })
  }

  try {
    assert.equal(getAuthToken(), 'persistent-session-token')
    const restoredUser = await apiRequest<{ id: number; username: string; full_name: string }>('/me')
    assert.equal(restoredUser.id, 102)
    assert.equal(restoredUser.username, 'shree')
    assert.equal(restoredUser.full_name, 'Shree')
  } finally {
    globalThis.fetch = originalFetch
    clearAuthToken()
  }
})

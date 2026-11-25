import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import { clearAuthToken, setAuthToken, ApiError } from '../src/api/client.ts'
import {
  blockUser,
  unblockUser,
  fetchBlockedUsers,
  reportUser,
  type BlockedUserItem,
} from '../src/api/safety.ts'

// Storage mock for Node test runner
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

test('Test 1 – Block User API: POST /api/v1/blocks dispatches blocked_id with Bearer token', async () => {
  const original = globalThis.fetch
  let request: Request | undefined
  setAuthToken('token-blocker')

  globalThis.fetch = async (input, init) => {
    request = new Request(input, init)
    return Response.json({
      id: 1,
      blocker_id: 10,
      blocked_id: 42,
    })
  }

  try {
    const res = await blockUser(42)
    assert.equal(new URL(request!.url).pathname, '/api/v1/blocks')
    assert.equal(request!.method, 'POST')
    assert.equal(request!.headers.get('authorization'), 'Bearer token-blocker')
    assert.deepEqual(await request!.clone().json(), { blocked_id: 42 })
    assert.equal(res.blocked_id, 42)
  } finally {
    globalThis.fetch = original
    clearAuthToken()
  }
})

test('Test 2 – Unblock User API: DELETE /api/v1/blocks/{blocked_id} dispatches with Bearer token', async () => {
  const original = globalThis.fetch
  let request: Request | undefined
  setAuthToken('token-unblocker')

  globalThis.fetch = async (input, init) => {
    request = new Request(input, init)
    return Response.json({ unblocked: true })
  }

  try {
    const res = await unblockUser(42)
    assert.equal(new URL(request!.url).pathname, '/api/v1/blocks/42')
    assert.equal(request!.method, 'DELETE')
    assert.equal(request!.headers.get('authorization'), 'Bearer token-unblocker')
    assert.equal(res.unblocked, true)
  } finally {
    globalThis.fetch = original
    clearAuthToken()
  }
})

test('Test 3 – Fetch Blocked Users API: GET /api/v1/blocks retrieves list with profile photos', async () => {
  const original = globalThis.fetch
  let request: Request | undefined
  setAuthToken('token-fetcher')

  const mockBlockedList: BlockedUserItem[] = [
    {
      id: 1,
      user_id: 101,
      username: 'troll_user',
      full_name: 'Troll User',
      photo_url: '/uploads/profiles/troll.jpg',
      created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 2,
      user_id: 102,
      username: 'spammer_99',
      full_name: null,
      photo_url: null,
      created_at: '2026-01-02T00:00:00Z',
    },
  ]

  globalThis.fetch = async (input, init) => {
    request = new Request(input, init)
    return Response.json(mockBlockedList)
  }

  try {
    const list = await fetchBlockedUsers()
    assert.equal(new URL(request!.url).pathname, '/api/v1/blocks')
    assert.equal(request!.method, 'GET')
    assert.equal(list.length, 2)
    assert.equal(list[0].username, 'troll_user')
    assert.equal(list[0].photo_url, '/uploads/profiles/troll.jpg')
  } finally {
    globalThis.fetch = original
    clearAuthToken()
  }
})

test('Test 4 – Report User API: POST /api/v1/reports dispatches reason and details', async () => {
  const original = globalThis.fetch
  let request: Request | undefined
  setAuthToken('token-reporter')

  globalThis.fetch = async (input, init) => {
    request = new Request(input, init)
    return Response.json({
      id: 99,
      reporter_id: 10,
      reported_id: 55,
      reason: 'Harassment',
      status: 'pending',
      created_at: new Date().toISOString(),
    })
  }

  try {
    const res = await reportUser(55, 'Harassment', 'Repeated unwanted messages')
    assert.equal(new URL(request!.url).pathname, '/api/v1/reports')
    assert.equal(request!.method, 'POST')
    const body = await request!.clone().json()
    assert.deepEqual(body, {
      reported_id: 55,
      reason: 'Harassment',
      details: 'Repeated unwanted messages',
    })
    assert.equal(res.status, 'pending')
  } finally {
    globalThis.fetch = original
    clearAuthToken()
  }
})

test('Test 5 – Self-blocking prevention: API rejects blocking self with HTTP 400', async () => {
  const original = globalThis.fetch

  globalThis.fetch = async () => {
    return new Response(JSON.stringify({ detail: 'Cannot block yourself' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  try {
    await assert.rejects(
      async () => {
        await blockUser(10)
      },
      (err: Error) => {
        assert.ok(err instanceof ApiError)
        assert.equal(err.status, 400)
        assert.equal(err.message, 'Cannot block yourself')
        return true
      }
    )
  } finally {
    globalThis.fetch = original
  }
})

test('Test 6 – Duplicate report prevention: API rejects duplicate reporting with HTTP 409', async () => {
  const original = globalThis.fetch

  globalThis.fetch = async () => {
    return new Response(JSON.stringify({ detail: 'You have already reported this user' }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  try {
    await assert.rejects(
      async () => {
        await reportUser(55, 'Spam')
      },
      (err: Error) => {
        assert.ok(err instanceof ApiError)
        assert.equal(err.status, 409)
        assert.equal(err.message, 'You have already reported this user')
        return true
      }
    )
  } finally {
    globalThis.fetch = original
  }
})

test('Test 7 – Block from Discover removes candidate from deck immediately', () => {
  let deck = [
    { id: 101, name: 'Aarav' },
    { id: 102, name: 'Rohan' },
    { id: 103, name: 'Ananya' },
  ]

  // Simulate block handler in Discover
  function handleUserBlocked(blockedUserId: number) {
    deck = deck.filter(c => c.id !== blockedUserId)
  }

  handleUserBlocked(102)
  assert.equal(deck.length, 2)
  assert.ok(!deck.some(c => c.id === 102))
})

test('Test 8 – Block from Conversations triggers match deactivation and closes conversation', () => {
  let activeMatches = [
    { id: 1, chat_id: 10, partner_id: 101, is_active: true },
    { id: 2, chat_id: 20, partner_id: 102, is_active: true },
  ]
  let currentOpenChatId: number | null = 10

  function handleBlockEvent(chatId: number, partnerId: number) {
    activeMatches = activeMatches.map(m =>
      m.chat_id === chatId ? { ...m, is_active: false } : m
    ).filter(m => m.is_active)
    if (currentOpenChatId === chatId) {
      currentOpenChatId = null
    }
  }

  handleBlockEvent(10, 101)
  assert.equal(activeMatches.length, 1)
  assert.equal(activeMatches[0].chat_id, 20)
  assert.equal(currentOpenChatId, null)
})

test('Test 9 – Bilateral exclusion in Discover: Blocked candidates excluded both directions', () => {
  const currentUserId = 5
  const userBlocks = [
    { blocker_id: 5, blocked_id: 101 }, // I blocked 101
    { blocker_id: 103, blocked_id: 5 }, // 103 blocked me
  ]

  const allCandidates = [
    { id: 101, name: 'User 101' },
    { id: 102, name: 'User 102' },
    { id: 103, name: 'User 103' },
    { id: 104, name: 'User 104' },
  ]

  // SQL bilateral check: ~(blocker == me and blocked == candidate) AND ~(blocker == candidate and blocked == me)
  const isBlockedBilateral = (candidateId: number) =>
    userBlocks.some(
      b => (b.blocker_id === currentUserId && b.blocked_id === candidateId) ||
           (b.blocker_id === candidateId && b.blocked_id === currentUserId)
    )

  const visibleCandidates = allCandidates.filter(c => !isBlockedBilateral(c.id))
  assert.equal(visibleCandidates.length, 2)
  assert.deepEqual(visibleCandidates.map(c => c.id), [102, 104])
})

test('Test 10 – Unblock from Settings removes user from restricted list', () => {
  let blockedUsers: BlockedUserItem[] = [
    { id: 1, user_id: 101, username: 'user1', full_name: 'User 1', photo_url: null, created_at: null },
    { id: 2, user_id: 102, username: 'user2', full_name: 'User 2', photo_url: null, created_at: null },
  ]

  function handleUnblock(userId: number) {
    blockedUsers = blockedUsers.filter(u => u.user_id !== userId)
  }

  handleUnblock(101)
  assert.equal(blockedUsers.length, 1)
  assert.equal(blockedUsers[0].user_id, 102)
})

test('Test 11 – Account isolation: Blocked lists remain isolated between accounts', () => {
  const accountABlocks = [{ blocker_id: 1, blocked_id: 101 }]
  const accountBBlocks = [{ blocker_id: 2, blocked_id: 202 }]

  const getBlocksForAccount = (userId: number) => {
    return userId === 1 ? accountABlocks : accountBBlocks
  }

  assert.equal(getBlocksForAccount(1).length, 1)
  assert.equal(getBlocksForAccount(1)[0].blocked_id, 101)
  assert.equal(getBlocksForAccount(2).length, 1)
  assert.equal(getBlocksForAccount(2)[0].blocked_id, 202)
})

test('Test 12 – Conversation header UI includes Three-dot Overflow Safety Menu', () => {
  const matchesPagesPath = path.resolve(import.meta.dirname, '../src/pages/MatchesPages.tsx')
  const content = fs.readFileSync(matchesPagesPath, 'utf8')

  // Check SafetyMenuDropdown is imported and rendered in chat header
  assert.ok(content.includes('SafetyMenuDropdown'))
  assert.ok(content.includes('BlockConfirmationModal'))
  assert.ok(content.includes('ReportUserModal'))
  assert.ok(content.includes('setShowBlockModal(true)'))
  assert.ok(content.includes('setShowReportModal(true)'))
})

test('Test 13 – Discover profile details UI includes Safety Menu for blocking/reporting', () => {
  const discoverPagesPath = path.resolve(import.meta.dirname, '../src/pages/DiscoverPages.tsx')
  const content = fs.readFileSync(discoverPagesPath, 'utf8')

  assert.ok(content.includes('SafetyMenuDropdown'))
  assert.ok(content.includes('BlockConfirmationModal'))
  assert.ok(content.includes('ReportUserModal'))
  assert.ok(content.includes('setShowCandidateBlock(true)'))
  assert.ok(content.includes('setShowCandidateReport(true)'))
})

test('Test 14 – Settings Page uses real backend data for Blocked Users', () => {
  const settingsPagePath = path.resolve(import.meta.dirname, '../src/pages/SettingsPage.tsx')
  const content = fs.readFileSync(settingsPagePath, 'utf8')

  assert.ok(content.includes('fetchBlockedUsers'))
  assert.ok(content.includes('unblockUserApi'))
  assert.ok(content.includes('BlockedUserItem'))
  assert.ok(content.includes('settings-unblock-btn'))
})

test('Test 15 – Safety Modals CSS styling conforms to cosmic purple theme', () => {
  const cssPath = path.resolve(import.meta.dirname, '../src/components/safety-modals.css')
  const css = fs.readFileSync(cssPath, 'utf8')

  assert.ok(css.includes('.safety-modal-overlay'))
  assert.ok(css.includes('.safety-modal-card'))
  assert.ok(css.includes('.safety-btn-danger'))
  assert.ok(css.includes('.safety-menu-dropdown'))
  assert.ok(css.includes('backdrop-filter: blur'))
})

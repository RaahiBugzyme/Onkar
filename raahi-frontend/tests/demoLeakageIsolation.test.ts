import test from 'node:test'
import assert from 'node:assert/strict'
import { isDemoModeEnabled, setDemoMode } from '../src/utils/demoEnvironment.ts'

// Mock environment for node:test runner
const storageMap = new Map<string, string>()
const mockLocalStorage = {
  getItem: (key: string) => storageMap.get(key) ?? null,
  setItem: (key: string, value: string) => { storageMap.set(key, value) },
  removeItem: (key: string) => { storageMap.delete(key) },
  clear: () => { storageMap.clear() }
}

if (!globalThis.localStorage) {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: mockLocalStorage
  })
}

test('Test 1 – Default isolation: Demo mode is disabled by default for ordinary sessions', () => {
  storageMap.clear()
  if (globalThis.window) {
    Object.defineProperty(globalThis.window, 'location', {
      configurable: true,
      value: { search: '' }
    })
  }
  assert.equal(isDemoModeEnabled(), false, 'Demo mode must be off by default')
})

test('Test 2 – Stale demo flag isolation: Authenticated sessions discard stale localStorage demo flags', () => {
  storageMap.clear()
  // Simulate active authenticated bearer token in localStorage
  storageMap.set('raahi.authToken.v1', 'real-bearer-token-12345')
  // Simulate stale demo flag left from previous manual test
  storageMap.set('raahi.demo_mode', 'true')

  assert.equal(isDemoModeEnabled(), false, 'Authenticated token must suppress stale demo mode')
  // Verify the stale flag was automatically purged from storage
  assert.equal(localStorage.getItem('raahi.demo_mode'), null, 'Stale raahi.demo_mode must be purged on check')
})

test('Test 3 – Explicit development testing: URL flag ?demo=true activates demo mode only when unauthenticated', () => {
  storageMap.clear()
  // Mock window.location.search
  const originalLocation = (globalThis as any).location
  Object.defineProperty(globalThis, 'location', {
    configurable: true,
    value: { search: '?demo=true' }
  })
  if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { search: '?demo=true' }
    })
  }

  assert.equal(isDemoModeEnabled(), true, 'Explicit ?demo=true URL parameter activates demo mode when unauthenticated')

  // CRITICAL: Now set auth token - even with ?demo=true, demo mode MUST be false!
  storageMap.set('raahi.authToken.v1', 'real-bearer-token-12345')
  assert.equal(isDemoModeEnabled(), false, 'Authenticated session must NEVER have demo mode enabled even with ?demo=true in URL')

  // Clean up location mock
  if (originalLocation) {
    Object.defineProperty(globalThis, 'location', { configurable: true, value: originalLocation })
  } else {
    delete (globalThis as any).location
  }
})

test('Test 4 – Unauthenticated dev toggle: setDemoMode works in clean dev environments', () => {
  storageMap.clear()
  setDemoMode(true)
  assert.equal(isDemoModeEnabled(), true, 'setDemoMode(true) enables demo mode when unauthenticated')
  setDemoMode(false)
  assert.equal(isDemoModeEnabled(), false, 'setDemoMode(false) disables demo mode')

  // When authenticated, setDemoMode must refuse to enable demo mode
  storageMap.set('raahi.authToken.v1', 'real-token')
  setDemoMode(true)
  assert.equal(isDemoModeEnabled(), false, 'setDemoMode(true) is rejected when user is authenticated')
  assert.equal(localStorage.getItem('raahi.demo_mode'), null, 'raahi.demo_mode is not saved when authenticated')
})

test('Test 5 – Token expiry does NOT silently activate demo mode', () => {
  storageMap.clear()
  // Token was cleared upon expiry
  assert.equal(localStorage.getItem('raahi.authToken.v1'), null)
  assert.equal(localStorage.getItem('raahi.demo_mode'), null)
  assert.equal(isDemoModeEnabled(), false, 'Demo mode remains false after token expiry')
})

test('Test 6 – URL parameters cannot override active auth session', () => {
  storageMap.clear()
  storageMap.set('raahi.authToken.v1', 'active-token-xyz')
  
  // Try URL ?demo=1
  Object.defineProperty(globalThis, 'location', {
    configurable: true,
    value: { search: '?demo=1' }
  })
  assert.equal(isDemoModeEnabled(), false, '?demo=1 cannot override active auth session')

  // Try URL ?demo=true
  Object.defineProperty(globalThis, 'location', {
    configurable: true,
    value: { search: '?demo=true' }
  })
  assert.equal(isDemoModeEnabled(), false, '?demo=true cannot override active auth session')
  delete (globalThis as any).location
})

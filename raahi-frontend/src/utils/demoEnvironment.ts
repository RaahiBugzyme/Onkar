/**
 * Safe Demo Mode Environment Utility
 *
 * Strict Isolation Rules:
 * 1. Authenticated user sessions must NEVER show demo profiles under any circumstances.
 *    If an active authentication token exists, demo mode is unconditionally disabled.
 * 2. Production builds cannot enable demo mode through URL parameters or stale localStorage flags.
 *    Only dedicated demo builds (VITE_ENABLE_DEMO_MODE === 'true') can activate demo mode in production.
 * 3. In non-production environments, demo mode is only active when explicitly requested via:
 *    - URL parameter `?demo=true` or `?demo=1`
 *    - localStorage item `raahi.demo_mode === 'true'`
 *    AND the user is NOT authenticated.
 * 4. Stale localStorage flags never override an active authenticated session.
 * 5. Expired tokens redirect to login and never silently activate demo mode.
 */

export function isDemoModeEnabled(): boolean {
  // CRITICAL RULE 1: If user has an active auth token in storage, demo mode is ALWAYS disabled.
  // Normal authenticated sessions must NEVER be overridden by URL params or stale demo flags.
  try {
    const storage = typeof window !== 'undefined' ? window.localStorage : globalThis.localStorage
    const hasAuthToken = Boolean(storage?.getItem('raahi.authToken.v1'))
    if (hasAuthToken) {
      if (storage?.getItem('raahi.demo_mode')) {
        storage.removeItem('raahi.demo_mode')
      }
      return false
    }
  } catch {
    // localStorage may be disabled or unavailable
  }

  // CRITICAL RULE 2: Production builds cannot enable demo mode through URL parameters or stale localStorage flags.
  // Only dedicated demo builds (VITE_ENABLE_DEMO_MODE === 'true') may run demo mode in production.
  const clientEnv = (import.meta as { env?: { PROD?: boolean; VITE_ENABLE_DEMO_MODE?: string } }).env
  const isProd = Boolean(clientEnv?.PROD)
  const isDedicatedDemoBuild = clientEnv?.VITE_ENABLE_DEMO_MODE === 'true'

  if (isProd && !isDedicatedDemoBuild) {
    return false
  }

  if (isDedicatedDemoBuild) {
    return true
  }

  // CRITICAL RULE 3: In development/test environments, explicitly requested by URL (?demo=true / ?demo=1)
  try {
    const loc = typeof window !== 'undefined' ? window.location : (globalThis as unknown as { location?: Location }).location
    if (loc?.search) {
      const params = new URLSearchParams(loc.search)
      const demoParam = params.get('demo')
      if (demoParam === 'true' || demoParam === '1') {
        return true
      }
    }
  } catch {
    // location might not be available in non-browser runtimes
  }

  // CRITICAL RULE 4: Explicit localStorage toggle (used in development/testing only when NOT logged in)
  try {
    const storage = typeof window !== 'undefined' ? window.localStorage : globalThis.localStorage
    if (storage?.getItem('raahi.demo_mode') === 'true') {
      return true
    }
  } catch {
    // localStorage may be disabled or unavailable
  }

  return false
}

export function setDemoMode(enabled: boolean): void {
  try {
    const storage = typeof window !== 'undefined' ? window.localStorage : globalThis.localStorage
    const hasAuthToken = Boolean(storage?.getItem('raahi.authToken.v1'))
    if (hasAuthToken) {
      // Never allow enabling demo mode while authenticated
      storage?.removeItem('raahi.demo_mode')
      return
    }
    if (enabled) {
      storage?.setItem('raahi.demo_mode', 'true')
    } else {
      storage?.removeItem('raahi.demo_mode')
    }
  } catch {
    // ignore
  }
}

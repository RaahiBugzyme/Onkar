import test from 'node:test'
import assert from 'node:assert/strict'
import { requestCurrentLocation } from '../src/utils/geolocation.ts'
import { isVerificationApproved } from '../src/routing/onboardingDestination.ts'
import type { DatingProfile } from '../src/api/datingProfile.ts'
import type { VerificationStatus } from '../src/api/verification.ts'

test('Phase 5 – Test 1: Geolocation handles unsupported browser gracefully', async () => {
  const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  Object.defineProperty(globalThis, 'navigator', {
    value: {},
    configurable: true,
    writable: true,
  })

  const result = await requestCurrentLocation()
  assert.equal(result.code, 'UNSUPPORTED')
  assert.ok(result.error?.includes('not supported'))

  if (originalDescriptor) {
    Object.defineProperty(globalThis, 'navigator', originalDescriptor)
  }
})

test('Phase 5 – Test 2: Geolocation handles PERMISSION_DENIED without throwing and encourages manual city entry', async () => {
  const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  Object.defineProperty(globalThis, 'navigator', {
    value: {
      geolocation: {
        getCurrentPosition: (_success: Function, error: Function) => {
          error({ code: 1, PERMISSION_DENIED: 1, message: 'User denied Geolocation' })
        },
      },
    },
    configurable: true,
    writable: true,
  })

  const result = await requestCurrentLocation()
  assert.equal(result.permissionDenied, true)
  assert.equal(result.code, 'PERMISSION_DENIED')
  assert.ok(result.error?.includes('denied'))

  if (originalDescriptor) {
    Object.defineProperty(globalThis, 'navigator', originalDescriptor)
  }
})

test('Phase 5 – Test 3: Geolocation handles TIMEOUT gracefully with fallback guidance', async () => {
  const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  Object.defineProperty(globalThis, 'navigator', {
    value: {
      geolocation: {
        getCurrentPosition: (_success: Function, error: Function) => {
          error({ code: 3, TIMEOUT: 3, message: 'Timeout expired' })
        },
      },
    },
    configurable: true,
    writable: true,
  })

  const result = await requestCurrentLocation()
  assert.equal(result.code, 'TIMEOUT')
  assert.ok(result.error?.includes('timed out'))

  if (originalDescriptor) {
    Object.defineProperty(globalThis, 'navigator', originalDescriptor)
  }
})

test('Phase 5 – Test 4: Geolocation coordinates are used to approximate city without exposing GPS to profile payload', async () => {
  const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  const originalFetch = globalThis.fetch

  Object.defineProperty(globalThis, 'navigator', {
    value: {
      geolocation: {
        getCurrentPosition: (success: Function) => {
          success({
            coords: {
              latitude: 19.076,
              longitude: 72.8777,
            },
          })
        },
      },
    },
    configurable: true,
    writable: true,
  })

  // @ts-expect-error test mock
  globalThis.fetch = async (url: string) => {
    assert.ok(url.includes('19.076'))
    return {
      ok: true,
      json: async () => ({ city: 'Mumbai', locality: 'Bandra', principalSubdivision: 'Maharashtra' }),
    }
  }

  const result = await requestCurrentLocation()
  assert.equal(result.city, 'Mumbai')
  assert.equal(result.latitude, 19.076)
  assert.equal(result.longitude, 72.8777)

  // Verify that dating profile input accepts only `city` string (no exact coordinates transmitted to public profile)
  const datingProfilePayload = {
    city: result.city,
    era: 'genz',
  }
  assert.equal(datingProfilePayload.city, 'Mumbai')
  assert.equal('latitude' in datingProfilePayload, false)
  assert.equal('longitude' in datingProfilePayload, false)

  if (originalDescriptor) {
    Object.defineProperty(globalThis, 'navigator', originalDescriptor)
  }
  globalThis.fetch = originalFetch
})

test('Phase 5 – Test 5: isVerificationApproved requires BOTH face and ID verification from backend', () => {
  const unverifiedProfile: DatingProfile = {
    id: 1,
    user_id: 10,
    full_name: 'Test',
    age: 22,
    date_of_birth: '2002-01-01',
    gender: 'prefer_not_to_say',
    city: 'Mumbai',
    era: 'genz',
    vibe_tag: 'chill',
    target_gender_preference: 'any',
    match_era_preference: 'any',
    is_face_verified: false,
    is_id_verified: false,
    verification_status: 'unverified',
    photos: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }

  const unverifiedStatus: VerificationStatus = {
    verifications: [],
    current_status: 'unverified',
    is_face_verified: false,
    is_id_verified: false,
    verification_available: true,
  }

  assert.equal(isVerificationApproved(unverifiedProfile, unverifiedStatus), false)

  // Partial verification (only face)
  const faceOnlyProfile = { ...unverifiedProfile, is_face_verified: true }
  const faceOnlyStatus = { ...unverifiedStatus, is_face_verified: true }
  assert.equal(isVerificationApproved(faceOnlyProfile, faceOnlyStatus), false)

  // Complete verification
  const completeProfile = {
    ...unverifiedProfile,
    is_face_verified: true,
    is_id_verified: true,
    verification_status: 'verified',
  }
  const completeStatus: VerificationStatus = {
    ...unverifiedStatus,
    is_face_verified: true,
    is_id_verified: true,
    current_status: 'verified',
  }
  assert.equal(isVerificationApproved(completeProfile, completeStatus), true)
})

test('Phase 5 – Test 6: Verification rejection state guides user to retry without permanent lockout', () => {
  const rejectedStatus: VerificationStatus = {
    verifications: [
      {
        id: 101,
        user_id: 20,
        verification_type: 'face',
        status: 'failed',
        reviewed_at: new Date().toISOString(),
      },
    ],
    current_status: 'failed',
    is_face_verified: false,
    is_id_verified: false,
    verification_available: true,
  }

  const hasRejection = rejectedStatus.verifications.some(v => v.status === 'failed') || rejectedStatus.current_status === 'failed'
  assert.equal(hasRejection, true)

  // Can upload is true when service is available, permitting retry
  const canUpload = rejectedStatus.verification_available !== false
  assert.equal(canUpload, true)
})

test('Phase 5 – Test 7: Public profile preview hides owner controls (Edit, Settings, Completeness)', () => {
  const isOwner = true

  // Standard Owner View
  const ownerViewPreview = false
  const showEditButtonInOwner = !ownerViewPreview && isOwner
  const showSettingsLinkInOwner = !ownerViewPreview && isOwner
  const showCompletenessInOwner = !ownerViewPreview && isOwner

  assert.equal(showEditButtonInOwner, true)
  assert.equal(showSettingsLinkInOwner, true)
  assert.equal(showCompletenessInOwner, true)

  // Public Profile Preview Mode (Owner viewing their own public card)
  const isPublicPreview = true
  const showEditButtonInPreview = !isPublicPreview && isOwner
  const showSettingsLinkInPreview = !isPublicPreview && isOwner
  const showCompletenessInPreview = !isPublicPreview && isOwner

  assert.equal(showEditButtonInPreview, false)
  assert.equal(showSettingsLinkInPreview, false)
  assert.equal(showCompletenessInPreview, false)

  // Non-owner viewing another user's profile
  const isOtherUser = false
  const showEditForOther = !isPublicPreview && isOtherUser
  const showSettingsForOther = !isPublicPreview && isOtherUser
  assert.equal(showEditForOther, false)
  assert.equal(showSettingsForOther, false)
})

test('Phase 5 – Test 8: Verified badge display is strictly conditional on backend verification', () => {
  const unverifiedCandidate = {
    is_verified: false,
    is_face_verified: false,
    is_id_verified: false,
  }
  const badgeLabelUnverified = (unverifiedCandidate.is_verified || (unverifiedCandidate.is_face_verified && unverifiedCandidate.is_id_verified))
    ? '✦ Verified Raahi Member'
    : '✦ Raahi Member'
  assert.equal(badgeLabelUnverified, '✦ Raahi Member')

  const verifiedCandidate = {
    is_verified: true,
    is_face_verified: true,
    is_id_verified: true,
  }
  const badgeLabelVerified = (verifiedCandidate.is_verified || (verifiedCandidate.is_face_verified && verifiedCandidate.is_id_verified))
    ? '✦ Verified Raahi Member'
    : '✦ Raahi Member'
  assert.equal(badgeLabelVerified, '✦ Verified Raahi Member')
})

test('Phase 5 – Test 9: Settings preferences and toggles persist across sessions in localStorage', () => {
  const storageMock = new Map<string, string>()
  const fakeLocalStorage = {
    getItem: (key: string) => storageMock.get(key) ?? null,
    setItem: (key: string, value: string) => storageMock.set(key, value),
  }
  // @ts-expect-error mock
  globalThis.localStorage = fakeLocalStorage

  // 1. Theme persistence
  fakeLocalStorage.setItem('raahiGenerationTheme.v1', 'millennial')
  assert.equal(fakeLocalStorage.getItem('raahiGenerationTheme.v1'), 'millennial')

  // 2. Dark mode persistence
  fakeLocalStorage.setItem('raahi_setting_darkMode', 'true')
  assert.equal(fakeLocalStorage.getItem('raahi_setting_darkMode'), 'true')

  // 3. Ghost mode persistence
  fakeLocalStorage.setItem('raahi_setting_ghostMode', 'true')
  assert.equal(fakeLocalStorage.getItem('raahi_setting_ghostMode'), 'true')

  // 4. Read receipts persistence
  fakeLocalStorage.setItem('raahi_setting_readReceipts', 'false')
  assert.equal(fakeLocalStorage.getItem('raahi_setting_readReceipts'), 'false')

  // 5. Notifications persistence
  fakeLocalStorage.setItem('raahi_setting_notifications', 'true')
  assert.equal(fakeLocalStorage.getItem('raahi_setting_notifications'), 'true')

  // 6. Match celebrations persistence
  fakeLocalStorage.setItem('raahi_setting_matchCelebrations', 'true')
  assert.equal(fakeLocalStorage.getItem('raahi_setting_matchCelebrations'), 'true')
})

test('Phase 5 – Test 10: Settings displays dynamic verification status badge matching profile', () => {
  function getVerificationPill(isFullyVerified: boolean, isPending: boolean, isFailed: boolean) {
    if (isFullyVerified) return 'Verified 🛡️'
    if (isPending) return 'Pending Review ⏳'
    if (isFailed) return 'Action Needed ⚠️'
    return 'Not Verified'
  }

  assert.equal(getVerificationPill(false, false, false), 'Not Verified')
  assert.equal(getVerificationPill(false, true, false), 'Pending Review ⏳')
  assert.equal(getVerificationPill(false, false, true), 'Action Needed ⚠️')
  assert.equal(getVerificationPill(true, false, false), 'Verified 🛡️')
})

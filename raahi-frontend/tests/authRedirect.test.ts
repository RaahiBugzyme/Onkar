import assert from 'node:assert/strict'
import test from 'node:test'
import { safeReturnPath } from '../src/routing/returnTo.ts'
import { isVerificationApproved, postAuthenticationDestination } from '../src/routing/onboardingDestination.ts'
import { shouldOfferDevelopmentVerificationContinuation } from '../src/routing/verificationContinuation.ts'
import type { DatingProfile } from '../src/api/datingProfile.ts'
import type { VerificationStatus } from '../src/api/verification.ts'

const approved: VerificationStatus = { verifications: [], current_status: 'verified', is_face_verified: true, is_id_verified: true, verification_available: true }

test('auth return path preserves internal destinations', () => {
  assert.equal(safeReturnPath('/conversations/42?from=matches'), '/conversations/42?from=matches')
})

test('auth return path rejects external and protocol-relative destinations', () => {
  assert.equal(safeReturnPath('https://example.test'), '/conversations')
  assert.equal(safeReturnPath('//example.test/path'), '/conversations')
  assert.equal(safeReturnPath('/\\\\example.test'), '/conversations')
})

test('login resumes onboarding or verification and only opens intended routes after approval', () => {
  const complete = { id: 1, is_face_verified: true, is_id_verified: true, verification_status: 'verified' } as DatingProfile
  const unverified = { id: 1, is_face_verified: false, is_id_verified: false, verification_status: 'unverified' } as DatingProfile
  assert.equal(postAuthenticationDestination(null), '/onboarding/era')
  assert.equal(postAuthenticationDestination(unverified), '/verification')
  assert.equal(postAuthenticationDestination(complete), '/verification')
  const pending = { ...complete, verification_status: 'pending' } as DatingProfile
  assert.equal(isVerificationApproved(pending, { ...approved, current_status: 'pending', is_face_verified: false, is_id_verified: false }), false)
  assert.equal(postAuthenticationDestination(pending, { ...approved, current_status: 'pending', is_face_verified: false, is_id_verified: false }), '/verification')
  assert.equal(postAuthenticationDestination(complete, approved), '/discover')
  assert.equal(postAuthenticationDestination(complete, approved, '/conversations/42?from=matches'), '/conversations/42?from=matches')
  assert.equal(postAuthenticationDestination(complete, approved, 'https://example.test'), '/conversations')
})

test('development continuation is offered only for pending review in a development build', () => {
  assert.equal(shouldOfferDevelopmentVerificationContinuation(true, true), true)
  assert.equal(shouldOfferDevelopmentVerificationContinuation(false, true), false)
  assert.equal(shouldOfferDevelopmentVerificationContinuation(true, false), false)
})

test('pending verification remains unapproved and production routing remains gated', () => {
  const complete = { id: 1, is_face_verified: true, is_id_verified: true, verification_status: 'pending' } as DatingProfile
  const pending = { ...approved, current_status: 'pending', is_face_verified: false, is_id_verified: false }
  assert.equal(isVerificationApproved(complete, pending), false)
  assert.equal(postAuthenticationDestination(complete, pending), '/verification')
  assert.equal(shouldOfferDevelopmentVerificationContinuation(false, true), false)
})

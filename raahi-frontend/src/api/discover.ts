import { apiRequest } from './client.ts'

export interface FeedProfile {
  user_id: number
  username: string
  full_name: string | null
  age: number | null
  city: string
  era: 'genz' | 'zillenial' | 'millennial'
  vibe_tag: string | null
  bio: string | null
  compatibility_score: number | null
  confidence_score: number | null
  adjusted_score: number | null
  recommendation_score: number | null
  score_type: 'profile_alignment' | null
  model_version: string | null
  prediction_provenance: string | null
  ranking_weights_validated: boolean
  matching_status: 'scored' | 'model_ineligible' | 'orientation_consent_required' | string
  is_face_verified: boolean
  is_id_verified: boolean
  verification_badge_required: boolean
}

export interface FeedResponse {
  profiles: FeedProfile[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface PublicProfile extends Omit<FeedProfile,
  'compatibility_score' | 'confidence_score' | 'adjusted_score' | 'recommendation_score' |
  'score_type' | 'model_version' | 'prediction_provenance' | 'ranking_weights_validated' |
  'matching_status' | 'is_face_verified' | 'is_id_verified' | 'verification_badge_required'
> {}

export interface SwipeResponse {
  id: number
  user_id: number
  target_user_id: number
  action: 'like' | 'pass' | 'superlike'
  created_at: string
  is_match?: boolean
}

export function fetchFeed(limit = 20, offset = 0) {
  return apiRequest<FeedResponse>(`/api/v1/feed?limit=${limit}&offset=${offset}`)
}

export function fetchPublicProfile(userId: number) {
  return apiRequest<PublicProfile>(`/api/v1/profile/${userId}`)
}

export function submitSwipe(targetUserId: number, action: SwipeResponse['action']) {
  return apiRequest<SwipeResponse>('/api/v1/swipe', {
    method: 'POST',
    body: JSON.stringify({ target_user_id: targetUserId, action }),
  })
}

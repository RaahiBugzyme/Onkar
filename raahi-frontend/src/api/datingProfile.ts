import { ApiError, apiRequest, uploadForm } from './client.ts'

export type DatingEra = 'genz' | 'zillenial' | 'millennial'
export type DatingGender = 'male' | 'female' | 'nonbinary' | 'other' | 'prefer_not_to_say'

export interface DatingProfile {
  id: number
  user_id: number
  date_of_birth: string | null
  gender: DatingGender
  sexual_orientation: string | null
  sexual_orientation_consent?: boolean
  behavioral_personalization_enabled?: boolean
  city: string
  era: DatingEra
  vibe_tag: string | null
  target_gender_preference?: string
  match_era_preference: string
  is_face_verified: boolean
  is_id_verified: boolean
  verification_status: 'unverified' | 'pending' | 'verified' | 'rejected'
  created_at: string
  updated_at: string
}

export interface DatingProfileInput {
  date_of_birth: string
  gender: DatingGender
  city: string
  era: DatingEra
  vibe_tag: string
  match_era_preference: string
  target_gender_preference: string
}

export async function getMyDatingProfile(): Promise<DatingProfile | null> {
  try {
    return await apiRequest<DatingProfile>('/api/v1/profile/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

export function createDatingProfile(input: DatingProfileInput) {
  return apiRequest<DatingProfile>('/api/v1/profile', { method: 'POST', body: JSON.stringify(input) })
}

export function updateDatingProfile(input: Partial<DatingProfileInput>) {
  return apiRequest<DatingProfile>('/api/v1/profile/me', { method: 'PUT', body: JSON.stringify(input) })
}

export interface ProfilePhoto {
  id: number
  photo_url: string
  is_primary: boolean
  display_order: number
}

export function uploadProfilePhoto(file: File, onProgress: (percentage: number) => void) {
  const form = new FormData()
  form.append('file', file)
  return uploadForm<ProfilePhoto>('/api/v1/profile/photos', form, onProgress)
}

export async function getMyProfilePhotos(): Promise<ProfilePhoto[]> {
  return apiRequest<ProfilePhoto[]>('/api/v1/profile/me/photos')
}

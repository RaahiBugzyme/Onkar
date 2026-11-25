import { apiRequest } from './client.ts'

export interface BlockResponse {
  id: number
  blocker_id: number
  blocked_id: number
}

export interface BlockedUserItem {
  id: number
  user_id: number
  username: string
  full_name: string | null
  photo_url: string | null
  created_at: string | null
}

export interface ReportResponse {
  id: number
  reporter_id: number
  reported_id: number
  reason: string
  status: string
  created_at: string
}

export function blockUser(blockedId: number): Promise<BlockResponse> {
  return apiRequest<BlockResponse>('/api/v1/blocks', {
    method: 'POST',
    body: JSON.stringify({ blocked_id: blockedId }),
  })
}

export function unblockUser(blockedId: number): Promise<{ unblocked: boolean }> {
  return apiRequest<{ unblocked: boolean }>(`/api/v1/blocks/${blockedId}`, {
    method: 'DELETE',
  })
}

export function fetchBlockedUsers(): Promise<BlockedUserItem[]> {
  return apiRequest<BlockedUserItem[]>('/api/v1/blocks')
}

export function reportUser(reportedId: number, reason: string, details?: string): Promise<ReportResponse> {
  return apiRequest<ReportResponse>('/api/v1/reports', {
    method: 'POST',
    body: JSON.stringify({ reported_id: reportedId, reason, details: details?.trim() || undefined }),
  })
}

import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { LoadingState } from './LoadingState'
import { useAuth } from '../state/AuthContext'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <LoadingState label="Checking your Raahi session…" />

  if (!user) {
    // Preserve explicitly public information routes
    const isPublicInfoRoute = location.pathname.startsWith('/privacy') || location.pathname.startsWith('/help')

    if (isPublicInfoRoute) {
      return <>{children}</>
    }

    const next = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace state={{ from: location }} />
  }

  return <>{children}</>
}

import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router'
import LandingPage from './pages/LandingPage'
import { IntegrationLayout } from './components/IntegrationLayout'
import { ProfilePage } from './pages/ProfilePage'
import { DiscoverPage, DiscoverProfilePage, DemoMatchPage } from './pages/DiscoverPages'
import { ConversationPage, ConversationsPage, MatchDetailPage, MatchesPage } from './pages/MatchesPages'
import { SettingsPage } from './pages/SettingsPage'
import { DiscoverRouteProvider } from './state/DiscoverContext'
import { ThemeProvider } from './state/ThemeContext'
import { AuthProvider } from './state/AuthContext'
import { RequireAuth } from './components/RequireAuth'
import { LoginPage } from './pages/LoginPage'
import { DatingProfileProvider } from './state/DatingProfileContext'
import { RegisterPage } from './pages/RegisterPage'
import VerificationPage from './pages/VerificationPage'

const OnboardingPage = lazy(() => import('./pages/OnboardingPage'))

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
        <DatingProfileProvider>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/verification" element={<RequireAuth><VerificationPage /></RequireAuth>} />
          <Route path="/onboarding" element={<RequireAuth><Navigate to="/onboarding/era" replace /></RequireAuth>} />
          <Route path="/onboarding/:step" element={<RequireAuth><Suspense fallback={null}><OnboardingPage /></Suspense></RequireAuth>} />
          <Route element={<RequireAuth><IntegrationLayout /></RequireAuth>}>
            <Route element={<DiscoverRouteProvider />}>
              <Route path="/discover" element={<DiscoverPage />} />
              <Route path="/discover/:profileId" element={<DiscoverProfilePage />} />
              <Route path="/matches/:profileId" element={<DemoMatchPage />} />
            </Route>
            <Route path="/matches" element={<MatchesPage />} />
            <Route path="/matches/:matchId/details" element={<MatchDetailPage />} />
            <Route path="/conversations" element={<ConversationsPage />} />
            <Route path="/conversations/:conversationId" element={<ConversationPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/profile/create" element={<ProfilePage />} />
            <Route path="/profile/edit" element={<ProfilePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </DatingProfileProvider>
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  )
}

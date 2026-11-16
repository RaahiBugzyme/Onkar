import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { AccountAccess } from '../components/AccountAccess'
import { Card } from '../components/Card'
import { LoadingState } from '../components/LoadingState'
import { PageContainer } from '../components/PageContainer'
import { useAuth } from '../state/AuthContext'
import { useDatingProfile } from '../state/DatingProfileContext'
import { postAuthenticationDestination } from '../routing/onboardingDestination'
import { getVerificationStatus } from '../api/verification'
import { RaahiWordmark } from '../components/RaahiWordmark'
const googleGIcon = new URL('../assets/google-g.svg', import.meta.url).href

export function LoginPage() {
  const { user, loading, logout } = useAuth()
  const { refreshProfile } = useDatingProfile()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const googleRequested = searchParams.get('provider') === 'google'
  const [googleNotice, setGoogleNotice] = useState(googleRequested)
  const [routeError, setRouteError] = useState('')
  const [accountDestination, setAccountDestination] = useState<string | null>(null)
  const [checkingAccount, setCheckingAccount] = useState(false)
  const requestedPath = searchParams.get('next')

  const resolveDestination = useCallback(async () => {
    const currentProfile = await refreshProfile()
    const verification = currentProfile ? await getVerificationStatus() : null
    return postAuthenticationDestination(currentProfile, verification, requestedPath)
  }, [refreshProfile, requestedPath])

  useEffect(() => {
    if (loading || !user) return
    let active = true
    setCheckingAccount(true)
    setRouteError('')
    void resolveDestination().then(destination => {
      if (active) setAccountDestination(destination)
    }).catch(reason => {
      if (active) setRouteError(reason instanceof Error ? reason.message : 'Could not check your saved profile.')
    }).finally(() => { if (active) setCheckingAccount(false) })
    return () => { active = false }
  }, [loading, user, resolveDestination])

  async function afterLogin() {
    setRouteError('')
    try {
      const destination = await resolveDestination()
      setAccountDestination(destination)
      navigate(destination, { replace: true })
    } catch (reason) {
      setRouteError(reason instanceof Error ? reason.message : 'Signed in, but account setup could not be checked. Try again.')
    }
  }

  if (loading) return <LoadingState label="Checking your Raahi session…" />
  if (user) return <PageContainer className="matches-page"><Card className="matches-empty-card matches-auth-card login-auth-card">
    <div className="login-branding"><RaahiWordmark className="login-wordmark" /><span>NO GHOSTING. JUST VIBES.</span></div>
    <p className="integration-eyebrow">ACCOUNT SESSION</p><h1>You’re already signed in</h1>
    <p>Signed in as <strong>{user.full_name || user.username}</strong>.</p>
    {checkingAccount && <p role="status" className="chat-muted">Checking your profile and verification status…</p>}
    {routeError && <><p className="chat-error" role="alert">{routeError}</p><button className="matches-outline-button" onClick={() => void afterLogin()}>Try again</button></>}
    {accountDestination && !checkingAccount && <button className="matches-primary-button login-primary-button" onClick={() => navigate(accountDestination, { replace: true })}>Continue to your account</button>}
    <button className="matches-outline-button login-switch-account" onClick={logout}>Sign out to use another account</button>
  </Card></PageContainer>

  return <PageContainer className="matches-page page-enter"><Card className="matches-empty-card matches-auth-card login-auth-card card-enter">
    <div className="login-branding"><RaahiWordmark className="login-wordmark" /><span>NO GHOSTING. JUST VIBES.</span></div>
    <p className="integration-eyebrow">WELCOME BACK</p>
    <h1>Sign in to continue</h1>
    <p>Sign in to continue to your saved profile and conversations.</p>
    {googleNotice && <p className="login-google-notice" role="status">Google account sign-in is not configured for Raahi yet. The available Google OAuth flow connects data to an existing account and cannot authenticate a Raahi account. Use your account email to continue.</p>}
    <AccountAccess onSignedIn={afterLogin} />
    <button type="button" className="login-google-button" onClick={() => setGoogleNotice(true)}><img src={googleGIcon} alt="" aria-hidden="true" />Continue with Google</button>
    <p className="login-signup-copy">Don't have an account? <Link to="/register">Sign up</Link></p>
    <Link className="matches-back-link login-back-link" to="/">Back to Raahi home</Link>
  </Card></PageContainer>
}

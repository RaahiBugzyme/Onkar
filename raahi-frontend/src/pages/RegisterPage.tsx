import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { ApiError } from '../api/client.ts'
import { registerAccount } from '../api/accounts'
import { Card } from '../components/Card'
import { LoadingState } from '../components/LoadingState'
import { PageContainer } from '../components/PageContainer'
import { useAuth } from '../state/AuthContext'
import { useDatingProfile } from '../state/DatingProfileContext'
import { postAuthenticationDestination } from '../routing/onboardingDestination'
import { RaahiWordmark } from '../components/RaahiWordmark'

export function RegisterPage() {
  const { user, loading, login, updateUser, logout } = useAuth()
  const { loading: profileLoading, setProfile, refreshProfile } = useDatingProfile()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [checkingDestination, setCheckingDestination] = useState(false)
  const [destination, setDestination] = useState<string | null>(null)

  async function resolveDestination() {
    const saved = await refreshProfile()
    if (saved) return postAuthenticationDestination(saved)
    return postAuthenticationDestination(null)
  }

  async function retryDestinationCheck() {
    setError('')
    setCheckingDestination(true)
    try { setDestination(await resolveDestination()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not check your account status.') }
    finally { setCheckingDestination(false) }
  }

  useEffect(() => {
    if (!user || busy) return
    let active = true
    setCheckingDestination(true)
    void resolveDestination().then(next => {
      if (active) setDestination(next)
    }).catch(reason => {
      if (active) {
        setError(reason instanceof Error ? reason.message : 'Could not check your account status.')
      }
    }).finally(() => { if (active) setCheckingDestination(false) })
    return () => { active = false }
  }, [user, busy, refreshProfile])

  if (loading || (user && profileLoading)) return <LoadingState label="Preparing your Raahi account…" />
  if (user && busy) return <LoadingState label="Setting up your Raahi account…" />
  if (user && checkingDestination && !error) return <LoadingState label="Checking your profile status…" />

  if (user) return <PageContainer className="matches-page"><Card className="matches-empty-card matches-auth-card register-auth-card">
    <div className="register-branding"><RaahiWordmark className="register-wordmark" /><span>NO GHOSTING. JUST VIBES.</span></div>
    <p className="integration-eyebrow">ACCOUNT SESSION</p><h1>You’re already signed in</h1><p>Signed in as <strong>{user.full_name || user.username}</strong>.</p>
    {error && <><p className="chat-error" role="alert">{error}</p><button type="button" className="matches-outline-button" onClick={() => void retryDestinationCheck()}>Retry account check</button></>}
    {destination && <button type="button" className="matches-primary-button" onClick={() => navigate(destination, { replace: true })}>Continue to your account</button>}
    <button type="button" className="matches-outline-button login-switch-account" onClick={logout}>Sign out to create another account</button>
  </Card></PageContainer>

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    const cleanedName = name.trim()
    const cleanedUsername = username.trim()
    if (cleanedName.length < 2 || cleanedName.length > 80) {
      setError('Name must be between 2 and 80 characters.')
      return
    }
    if (!/^[A-Za-z0-9_.-]{3,30}$/.test(cleanedUsername)) {
      setError('Username must be 3–30 characters and use letters, numbers, dots, underscores or hyphens.')
      return
    }
    if (password.length < 8 || password.length > 128) {
      setError('Password must be between 8 and 128 characters.')
      return
    }
    setBusy(true)
    try {
      await registerAccount({ username: cleanedUsername, email: email.trim(), password })
      await login(email.trim(), password)
      setProfile(null)
      try { await updateUser({ full_name: cleanedName }) } catch { /* Profile setup can still retry the name after account creation. */ }
      setPassword('')
      navigate('/onboarding/era', { replace: true })
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Could not create your account. Check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  return <PageContainer className="matches-page page-enter"><Card className="matches-empty-card matches-auth-card register-auth-card card-enter">
    <div className="register-branding"><RaahiWordmark className="register-wordmark" /><span>NO GHOSTING. JUST VIBES.</span></div>
    <p className="integration-eyebrow">YOUR NEXT CHAPTER</p>
    <h1>Create your Raahi account</h1>
    <p>One account for your profile, matches and conversations.</p>
    <form className="account-login-form" onSubmit={submit}>
      <label>Name<input type="text" autoComplete="name" minLength={2} maxLength={80} value={name} onChange={event => setName(event.currentTarget.value)} required /></label>
      <label>Username<input type="text" autoComplete="username" minLength={3} maxLength={30} pattern="[A-Za-z0-9_.-]+" value={username} onChange={event => setUsername(event.currentTarget.value)} required /></label>
      <label>Email<input type="email" autoComplete="email" maxLength={254} value={email} onChange={event => setEmail(event.currentTarget.value)} required /></label>
      <label>Password<input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={password} onChange={event => setPassword(event.currentTarget.value)} required /></label>
      {error && <p className="chat-error" role="alert">{error}</p>}
      <button type="submit" className="matches-primary-button" disabled={busy}>{busy ? 'Creating your account…' : 'Create account'}</button>
    </form>
    <p className="chat-muted">Already have an account? <Link to="/login">Log in</Link></p>
  </Card></PageContainer>
}

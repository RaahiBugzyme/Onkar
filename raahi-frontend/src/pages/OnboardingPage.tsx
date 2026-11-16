import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { createDatingProfile, updateDatingProfile, uploadProfilePhoto, type DatingProfileInput, type DatingGender } from '../api/datingProfile'
import { useAuth } from '../state/AuthContext'
import { useDatingProfile } from '../state/DatingProfileContext'
import { useTheme } from '../state/ThemeContext'
import { generationThemes, type GenerationId } from '../data/generations'
import '../styles/onboarding-flow.css'
import '../styles/match-era.css'

type Draft = { era?: GenerationId; vibe?: string; target?: string; matchEra?: string }
const DRAFT_KEY = 'raahi.onboardingDraft.v2'
function readDraft(): Draft {
  try { return JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? '{}') as Draft } catch { return {} }
}
function saveDraft(draft: Draft) {
  try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft)) } catch { /* API remains the source of truth after completion. */ }
}
function normalizeStep(value: string | undefined) {
  return ['era', 'situationship', 'preferences', 'profile'].includes(value ?? '') ? value! : 'era'
}

export default function OnboardingPage() {
  const step = normalizeStep(useParams().step)
  const navigate = useNavigate()
  const { user, updateUser } = useAuth()
  const { profile, loading: profileLoading, refreshProfile, setProfile } = useDatingProfile()
  const { generation, setGeneration } = useTheme()
  const [draft, setDraft] = useState<Draft>(readDraft)
  const selectedEra = draft.era ?? profile?.era ?? generation
  const selectedTheme = generationThemes[selectedEra]
  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [dob, setDob] = useState(profile?.date_of_birth ?? '')
  const [gender, setGender] = useState<DatingGender>(profile?.gender ?? 'prefer_not_to_say')
  const [targetGender, setTargetGender] = useState(profile?.target_gender_preference ?? draft.target ?? 'any')
  const [city, setCity] = useState(profile?.city ?? '')
  const [bio, setBio] = useState(user?.bio ?? '')
  const [matchEra, setMatchEra] = useState(profile?.match_era_preference ?? 'any')
  const [photos, setPhotos] = useState<File[]>([])
  const [photoProgress, setPhotoProgress] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    setGeneration(selectedEra)
  }, [selectedEra, setGeneration])

  useEffect(() => {
    if (!profile) return
    setDob(profile.date_of_birth ?? '')
    setGender(profile.gender)
    setTargetGender(profile.target_gender_preference ?? 'any')
    setCity(profile.city)
    setMatchEra(profile.match_era_preference)
  }, [profile])

  const stepIndex = ['era', 'situationship', 'preferences', 'profile'].indexOf(step)

  function updateDraft(changes: Draft) {
    setDraft(current => {
      const next = { ...current, ...changes }
      saveDraft(next)
      return next
    })
  }

  function next(to: string) {
    setError('')
    navigate(`/onboarding/${to}`)
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (fullName.trim().length < 2) return setError('Enter a name with at least 2 characters.')
    if (!dob || !city.trim()) return setError('Date of birth and location are required.')
    if (new Date(dob).getTime() > Date.now()) return setError('Date of birth must be in the past.')
    if (bio.length > 500) return setError('Bio must be 500 characters or fewer.')
    setBusy(true)
    try {
      const payload: DatingProfileInput = {
        date_of_birth: dob, gender, city: city.trim(), era: selectedEra,
        vibe_tag: draft.vibe ?? profile?.vibe_tag ?? '',
        target_gender_preference: targetGender,
        match_era_preference: draft.matchEra ?? profile?.match_era_preference ?? matchEra,
      }
      const saved = profile ? await updateDatingProfile(payload) : await createDatingProfile(payload)
      setProfile(saved)
      await updateUser({ full_name: fullName.trim(), bio: bio.trim() })
      if (photos.length) {
        for (const file of photos) await uploadProfilePhoto(file, setPhotoProgress)
      }
      try { sessionStorage.removeItem(DRAFT_KEY) } catch { /* ignore unavailable storage */ }
      await refreshProfile()
      setSuccess('Your profile details are saved. Continue to identity verification.')
      navigate('/verification', { replace: true })
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Could not save your profile. Check your connection and try again.')
    } finally { setBusy(false) }
  }

  if (profileLoading) return <main className="onboarding-flow"><p role="status">Loading your saved profile…</p></main>
  if (!user) return <Navigate to="/login" replace />
  if (profile && step !== 'profile') return <Navigate to="/verification" replace />
  if (!profile && step !== 'era' && !draft.era) return <Navigate to="/onboarding/era" replace />
  if (!profile && step === 'preferences' && !draft.vibe) return <Navigate to="/onboarding/situationship" replace />
  if (!profile && step === 'profile' && !draft.matchEra) return <Navigate to="/onboarding/preferences" replace />

  return <main className="onboarding-flow" data-theme={selectedEra}>
    <div className="onboarding-flow-glow" />
    <header className="onboarding-flow-header"><Link to="/verification" aria-label="Back to verification">← Back</Link><span>{selectedTheme.emoji} {selectedTheme.name}</span></header>
    <div className="onboarding-flow-progress" aria-label={`Step ${stepIndex + 1} of 4`}>{[0,1,2,3].map(index => <span key={index} className={index <= stepIndex ? 'active' : ''} />)}</div>
    <section className="onboarding-flow-content">
      <p className="onboarding-flow-kicker">STEP {stepIndex + 1} OF 4</p>
      {step === 'era' && <>
        <h1>Pick your era, bestie <span className="e e-wiggle">👾</span></h1><p className="onboarding-flow-sub">Choose the energy that feels most like you.</p>
        <div className="onboarding-choice-grid fiu">{(Object.keys(generationThemes) as GenerationId[]).map(id => {
          const theme = generationThemes[id]
          return <button type="button" key={id} onClick={() => { updateDraft({ era: id }); setGeneration(id) }} className={`onboarding-choice era-choice interactive-tap ${selectedEra === id ? 'selected' : ''}`}><span className={`choice-emoji e ${theme.emojiAnimation}`}>{theme.emoji}</span><strong>{theme.name}</strong><small>{theme.eraDescription}</small><span className="choice-tags">{theme.eraTags.join(' · ')}</span></button>
        })}</div>
        <button className="onboarding-flow-primary btn-cta" disabled={!draft.era && !profile?.era} onClick={() => next('situationship')}>Next <span className="btn-arrow">→</span></button>
      </>}
      {step === 'situationship' && <>
        <h1>{selectedTheme.vibeTitle} <span className={`e ${selectedTheme.vibeHeadingAnimation}`}>{selectedTheme.vibeHeadingEmoji}</span></h1><p className="onboarding-flow-sub">{selectedTheme.vibeSubtitle}</p>
        <div className="onboarding-choice-grid fiu">{selectedTheme.vibes.map(vibe => <button type="button" key={vibe.name} onClick={() => updateDraft({ vibe: vibe.name })} className={`onboarding-choice vibe-choice interactive-tap ${draft.vibe === vibe.name ? 'selected' : ''}`}><span className={`choice-emoji e ${vibe.animation}`}>{vibe.icon}</span><strong>{vibe.name}</strong><small>{vibe.description}</small></button>)}</div>
        <div className="onboarding-flow-actions"><button className="onboarding-flow-secondary" onClick={() => next('era')}>← Back</button><button className="onboarding-flow-primary btn-cta" disabled={!draft.vibe && !profile?.vibe_tag} onClick={() => next('preferences')}>Next <span className="btn-arrow">→</span></button></div>
      </>}
      {step === 'preferences' && <>
        <h1>{selectedTheme.matchTitle} <span className={`e match-era-heading-emoji ${selectedTheme.matchHeadingAnimation}`}>{selectedTheme.matchHeadingEmoji}</span></h1><p className="onboarding-flow-sub">Pick the era you want to match with.</p>
        <div className="match-grid-v3" role="radiogroup" aria-label="Choose the era you want to match with">
          {([
            { id: 'genz', emoji: '💀', animation: 'e-shake', name: 'Gen Z', description: 'TikTok-brained, chronically online' },
            { id: 'zillenial', emoji: '🎭', animation: 'e-flip', name: 'Zillenial', description: 'Gets both eras, chaos but self-aware' },
            { id: 'millennial', emoji: '✌️', animation: 'e-wave', name: 'Millennial', description: 'Emotionally available (mostly)' },
            { id: 'any', emoji: '🌈', animation: 'e-spin', name: 'Open to any era', description: "Love doesn't check a birth certificate" },
          ] as const).map(option => <button type="button" role="radio" aria-checked={draft.matchEra === option.id} key={option.id} onClick={() => updateDraft({ matchEra: option.id })} className={`match-card-v3 ${draft.matchEra === option.id ? 'selected' : ''}`} data-match={option.id}>
            <span className="match-emoji-wrap-v3"><span className={`e ${option.animation}`}>{option.emoji}</span></span><span className="match-info-v3"><strong className="match-name-v3">{option.name}</strong><small className="match-desc-v3">{option.description}</small></span><span className="match-radio-v3" aria-hidden="true" />
          </button>)}
        </div>
        <div className="onboarding-flow-actions"><button className="onboarding-flow-secondary" onClick={() => next('situationship')}>← Back</button><button className="onboarding-flow-primary match-era-cta btn-cta" disabled={!draft.matchEra} onClick={() => next('profile')}>Show me my matches <span className="btn-arrow">→</span></button></div>
      </>}
      {step === 'profile' && <>
        <h1>Complete your profile ✨</h1><p className="onboarding-flow-sub">A few details help us show you eligible people.</p>
        <form className="onboarding-profile-form" onSubmit={saveProfile}>
          <label>Display name<input required minLength={2} maxLength={80} value={fullName} onChange={e => setFullName(e.currentTarget.value)} autoComplete="name" /></label>
          <label>Date of birth<input required type="date" max={new Date().toISOString().slice(0,10)} value={dob} onChange={e => setDob(e.currentTarget.value)} /></label>
          <label>Gender<select required value={gender} onChange={e => setGender(e.currentTarget.value as DatingGender)}><option value="prefer_not_to_say">Prefer not to say</option><option value="female">Female</option><option value="male">Male</option><option value="nonbinary">Non-binary</option><option value="other">Other</option></select></label>
          <label>City<input required maxLength={60} value={city} onChange={e => setCity(e.currentTarget.value)} autoComplete="address-level2" /></label>
          <label>Bio<textarea maxLength={500} value={bio} onChange={e => setBio(e.currentTarget.value)} rows={3} /></label>
          <label>Who would you like to discover?<select value={targetGender} onChange={e => setTargetGender(e.currentTarget.value)}><option value="any">Everyone</option><option value="female">Women</option><option value="male">Men</option><option value="nonbinary">Non-binary people</option><option value="other">Other genders</option></select></label>
          <label>Preferred match era<select value={draft.matchEra ?? matchEra} onChange={e => updateDraft({ matchEra: e.currentTarget.value })}><option value="any">Open to any era</option><option value="genz">Gen Z</option><option value="zillenial">Zillenial</option><option value="millennial">Millennial</option></select></label>
          <label>Profile photos<input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={e => setPhotos(Array.from(e.currentTarget.files ?? []))} /></label>
          {photoProgress > 0 && <p role="status">Photo upload: {photoProgress}%</p>}
          <p className="onboarding-flow-privacy">Interests are not currently supported by the profile API, so they are not collected as if they could be saved. Photos are private to your own profile until backend visibility is provided.</p>
          {error && <p className="onboarding-flow-error" role="alert">{error}</p>}{success && <p role="status">{success}</p>}
          <div className="onboarding-flow-actions"><button type="button" className="onboarding-flow-secondary" onClick={() => next('preferences')}>← Back</button><button className="onboarding-flow-primary" disabled={busy}>{busy ? 'Saving…' : 'Save & continue'}</button></div>
        </form>
      </>}
    </section>
  </main>
}

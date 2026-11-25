import { useEffect, useRef, useState } from 'react'
import { blockUser, reportUser } from '../api/safety'
import { ApiError } from '../api/client'
import './safety-modals.css'

export interface BlockConfirmationModalProps {
  isOpen: boolean
  targetUserId: number
  targetName: string
  isMatchOrChat?: boolean
  onClose: () => void
  onSuccess: () => void
}

export function BlockConfirmationModal({
  isOpen,
  targetUserId,
  targetName,
  isMatchOrChat = false,
  onClose,
  onSuccess,
}: BlockConfirmationModalProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setError(null)
      setBusy(false)
    }
  }, [isOpen])

  if (!isOpen) return null

  async function handleConfirm() {
    setBusy(true)
    setError(null)
    try {
      await blockUser(targetUserId)
      onSuccess()
      onClose()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Could not block user.')
      setBusy(false)
    }
  }

  return (
    <div className="safety-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="block-dialog-title" onClick={onClose}>
      <div className="safety-modal-card" onClick={e => e.stopPropagation()}>
        <div className="safety-modal-header">
          <div className="safety-modal-icon-badge" aria-hidden="true">
            🚫
          </div>
          <h3 id="block-dialog-title" className="safety-modal-title">
            Block {targetName}?
          </h3>
        </div>

        <p className="safety-modal-desc">
          Are you sure you want to block <strong>{targetName}</strong>?
          {isMatchOrChat ? (
            <> This will immediately <strong>unmatch</strong> you, close your conversation, and remove your mutual match. You will no longer see each other anywhere on Raahi.</>
          ) : (
            <> They will be permanently removed from your Discover deck and cannot message or view your profile.</>
          )}
        </p>

        {error && <div className="safety-modal-error" role="alert">{error}</div>}

        <div className="safety-modal-actions">
          <button
            type="button"
            className="safety-btn-cancel"
            onClick={onClose}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="safety-btn-danger"
            onClick={() => void handleConfirm()}
            disabled={busy}
          >
            {busy ? 'Blocking…' : 'Block User'}
          </button>
        </div>
      </div>
    </div>
  )
}

export interface ReportUserModalProps {
  isOpen: boolean
  targetUserId: number
  targetName: string
  onClose: () => void
  onSuccess: (message: string) => void
}

const REPORT_REASONS = [
  'Harassment or inappropriate messages',
  'Inappropriate or offensive photos',
  'Fake profile or impersonation',
  'Spam, advertising or commercial promotion',
  'Underage account',
  'Other safety or community violation',
]

export function ReportUserModal({
  isOpen,
  targetUserId,
  targetName,
  onClose,
  onSuccess,
}: ReportUserModalProps) {
  const [reason, setReason] = useState(REPORT_REASONS[0])
  const [details, setDetails] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setReason(REPORT_REASONS[0])
      setDetails('')
      setError(null)
      setBusy(false)
    }
  }, [isOpen])

  if (!isOpen) return null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await reportUser(targetUserId, reason, details)
      onSuccess(`Thank you. Your report against ${targetName} has been submitted for review.`)
      onClose()
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setError('You have already submitted a report for this profile.')
      } else {
        setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Could not submit report.')
      }
      setBusy(false)
    }
  }

  return (
    <div className="safety-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="report-dialog-title" onClick={onClose}>
      <div className="safety-modal-card" onClick={e => e.stopPropagation()}>
        <div className="safety-modal-header">
          <div className="safety-modal-icon-badge warning" aria-hidden="true">
            🛡️
          </div>
          <h3 id="report-dialog-title" className="safety-modal-title">
            Report {targetName}
          </h3>
        </div>

        <p className="safety-modal-desc">
          Your report is anonymous. Help keep Raahi safe by letting our moderation team know what happened.
        </p>

        <form onSubmit={e => void handleSubmit(e)}>
          <div className="safety-modal-field">
            <label htmlFor="report-reason-select" className="safety-modal-label">
              Reason for report
            </label>
            <select
              id="report-reason-select"
              className="safety-modal-select"
              value={reason}
              onChange={e => setReason(e.target.value)}
              disabled={busy}
            >
              {REPORT_REASONS.map(r => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div className="safety-modal-field">
            <label htmlFor="report-details-textarea" className="safety-modal-label">
              Additional details (optional)
            </label>
            <textarea
              id="report-details-textarea"
              className="safety-modal-textarea"
              placeholder="Tell us what occurred or share relevant context…"
              value={details}
              onChange={e => setDetails(e.target.value)}
              disabled={busy}
              rows={3}
            />
          </div>

          {error && <div className="safety-modal-error" role="alert">{error}</div>}

          <div className="safety-modal-actions">
            <button
              type="button"
              className="safety-btn-cancel"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="safety-btn-primary"
              disabled={busy}
            >
              {busy ? 'Submitting…' : 'Submit Report'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function SafetyMenuDropdown({
  onOpenReport,
  onOpenBlock,
  buttonClassName = 'safety-menu-trigger',
  ariaLabel = 'Safety and conversation options',
}: {
  onOpenReport: () => void
  onOpenBlock: () => void
  buttonClassName?: string
  ariaLabel?: string
}) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [open])

  return (
    <div className="safety-menu-container" ref={menuRef}>
      <button
        type="button"
        className={`${buttonClassName}${open ? ' active' : ''}`}
        onClick={() => setOpen(prev => !prev)}
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="menu"
        title="More options"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="5" r="1.5" fill="currentColor"/>
          <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
          <circle cx="12" cy="19" r="1.5" fill="currentColor"/>
        </svg>
      </button>

      {open && (
        <div className="safety-menu-dropdown" role="menu">
          <button
            type="button"
            className="safety-menu-item"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onOpenReport()
            }}
          >
            <span className="safety-menu-item-icon" aria-hidden="true">🛡️</span>
            Report User
          </button>
          <button
            type="button"
            className="safety-menu-item danger"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onOpenBlock()
            }}
          >
            <span className="safety-menu-item-icon" aria-hidden="true">🚫</span>
            Block User
          </button>
        </div>
      )}
    </div>
  )
}

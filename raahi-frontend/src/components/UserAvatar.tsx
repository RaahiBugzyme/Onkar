import { useState, useEffect, type CSSProperties } from 'react'
import { resolveMediaUrl } from '../api/client'

export interface UserAvatarProps {
  src?: string | null
  name: string
  size?: number | string
  className?: string
  style?: CSSProperties
  alt?: string
  ringColor?: string
  cornerEmoji?: string
}

export function UserAvatar({
  src,
  name,
  size,
  className = '',
  style,
  alt,
  ringColor,
  cornerEmoji,
}: UserAvatarProps) {
  const [hasError, setHasError] = useState(false)

  useEffect(() => {
    setHasError(false)
  }, [src])

  const initial = (name.trim()[0] || 'R').toUpperCase()
  const resolvedUrl = resolveMediaUrl(src)

  const sizeStyle: CSSProperties = size
    ? {
        width: typeof size === 'number' ? `${size}px` : size,
        height: typeof size === 'number' ? `${size}px` : size,
        minWidth: typeof size === 'number' ? `${size}px` : size,
        minHeight: typeof size === 'number' ? `${size}px` : size,
      }
    : {}

  const ringStyle: CSSProperties = ringColor
    ? {
        borderColor: ringColor,
        boxShadow: `0 0 14px ${ringColor}55`,
      }
    : {}

  return (
    <div
      className={`user-avatar-root ${className}`.trim()}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: '50%',
        overflow: 'hidden',
        background: 'var(--bg-mid, #150a28)',
        ...sizeStyle,
        ...ringStyle,
        ...style,
      }}
    >
      {resolvedUrl && !hasError ? (
        <img
          src={resolvedUrl}
          alt={alt || name}
          className="user-avatar-img"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            display: 'block',
          }}
          onError={() => setHasError(true)}
        />
      ) : (
        <span
          className="user-avatar-initial"
          style={{
            fontFamily: "'Syne', sans-serif",
            fontWeight: 800,
            color: '#fff',
            userSelect: 'none',
          }}
        >
          {initial}
        </span>
      )}
      {cornerEmoji && (
        <span
          className="user-avatar-corner"
          aria-hidden="true"
          style={{
            position: 'absolute',
            bottom: -2,
            right: -2,
            fontSize: '0.85em',
            lineHeight: 1,
            pointerEvents: 'none',
          }}
        >
          {cornerEmoji}
        </span>
      )}
    </div>
  )
}

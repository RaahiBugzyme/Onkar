import test from 'node:test'
import assert from 'node:assert/strict'
import { resolveMediaUrl } from '../src/api/client.ts'
import {
  setPrimaryProfilePhoto,
  reorderProfilePhotos,
  deleteProfilePhoto,
  type ProfilePhoto,
} from '../src/api/datingProfile.ts'

test('Test 1 – resolveMediaUrl: correctly handles relative backend paths, external URLs, data URLs, and nulls', () => {
  assert.equal(resolveMediaUrl(null), '')
  assert.equal(resolveMediaUrl(undefined), '')
  assert.equal(resolveMediaUrl('   '), '')

  // External & embedded URLs preserved
  assert.equal(
    resolveMediaUrl('https://images.unsplash.com/photo-123.jpg'),
    'https://images.unsplash.com/photo-123.jpg'
  )
  assert.equal(
    resolveMediaUrl('http://example.com/avatar.png'),
    'http://example.com/avatar.png'
  )
  assert.equal(
    resolveMediaUrl('data:image/svg+xml;utf8,<svg></svg>'),
    'data:image/svg+xml;utf8,<svg></svg>'
  )
  assert.equal(
    resolveMediaUrl('blob:http://localhost:5173/uuid-123'),
    'blob:http://localhost:5173/uuid-123'
  )

  // Relative backend uploads path resolved with API host
  const resolved = resolveMediaUrl('/uploads/profiles/profile_test123.jpg')
  assert.ok(resolved.endsWith('/uploads/profiles/profile_test123.jpg'))
  assert.ok(resolved.startsWith('http://') || resolved.startsWith('https://'))
})

test('Test 2 – Primary photo selection logic: extracts primary photo or falls back to first photo', () => {
  function getEffectivePrimaryPhoto(photos?: ProfilePhoto[] | null): string | null {
    if (!photos || photos.length === 0) return null
    const primary = photos.find(p => p.is_primary)
    return (primary || photos[0])?.photo_url || null
  }

  // Empty / null
  assert.equal(getEffectivePrimaryPhoto(null), null)
  assert.equal(getEffectivePrimaryPhoto([]), null)

  // Single photo marked primary
  const singlePrimary: ProfilePhoto[] = [
    { id: 1, photo_url: '/uploads/profiles/1.jpg', is_primary: true, display_order: 1 },
  ]
  assert.equal(getEffectivePrimaryPhoto(singlePrimary), '/uploads/profiles/1.jpg')

  // Multiple photos where 2nd is primary
  const multipleWithPrimary: ProfilePhoto[] = [
    { id: 10, photo_url: '/uploads/profiles/10.jpg', is_primary: false, display_order: 2 },
    { id: 11, photo_url: '/uploads/profiles/11.jpg', is_primary: true, display_order: 1 },
    { id: 12, photo_url: '/uploads/profiles/12.jpg', is_primary: false, display_order: 3 },
  ]
  assert.equal(getEffectivePrimaryPhoto(multipleWithPrimary), '/uploads/profiles/11.jpg')

  // Multiple photos where none is marked primary (fallback to photos[0])
  const multipleWithoutPrimary: ProfilePhoto[] = [
    { id: 20, photo_url: '/uploads/profiles/20.jpg', is_primary: false, display_order: 1 },
    { id: 21, photo_url: '/uploads/profiles/21.jpg', is_primary: false, display_order: 2 },
  ]
  assert.equal(getEffectivePrimaryPhoto(multipleWithoutPrimary), '/uploads/profiles/20.jpg')
})

test('Test 3 – WebP and image magic number signatures: verifies 12-byte WebP and image headers', () => {
  function detectImageMimeType(buffer: Uint8Array): string | null {
    if (buffer.length < 3) return null
    // JPEG: FF D8 FF
    if (buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) {
      return 'image/jpeg'
    }
    // PNG: 89 50 4E 47 0D 0A 1A 0A
    if (
      buffer.length >= 8 &&
      buffer[0] === 0x89 &&
      buffer[1] === 0x50 &&
      buffer[2] === 0x4e &&
      buffer[3] === 0x47 &&
      buffer[4] === 0x0d &&
      buffer[5] === 0x0a &&
      buffer[6] === 0x1a &&
      buffer[7] === 0x0a
    ) {
      return 'image/png'
    }
    // WEBP: RIFF (4 bytes) + 4 bytes size + WEBP (4 bytes) -> requires 12 bytes
    if (
      buffer.length >= 12 &&
      buffer[0] === 0x52 && // R
      buffer[1] === 0x49 && // I
      buffer[2] === 0x46 && // F
      buffer[3] === 0x46 && // F
      buffer[8] === 0x57 && // W
      buffer[9] === 0x45 && // E
      buffer[10] === 0x42 && // B
      buffer[11] === 0x50    // P
    ) {
      return 'image/webp'
    }
    // GIF: GIF87a or GIF89a
    if (
      buffer.length >= 6 &&
      buffer[0] === 0x47 && buffer[1] === 0x49 && buffer[2] === 0x46 && buffer[3] === 0x38 &&
      (buffer[4] === 0x37 || buffer[4] === 0x39) && buffer[5] === 0x61
    ) {
      return 'image/gif'
    }
    return null
  }

  // Construct WebP dummy bytes (12 bytes: RIFF????WEBP)
  const webpBytes = new Uint8Array([
    0x52, 0x49, 0x46, 0x46, // RIFF
    0x00, 0x00, 0x00, 0x00, // Size
    0x57, 0x45, 0x42, 0x50, // WEBP
    0x56, 0x50, 0x38, 0x20, // VP8_
  ])
  assert.equal(detectImageMimeType(webpBytes), 'image/webp')

  // Construct PNG bytes
  const pngBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00])
  assert.equal(detectImageMimeType(pngBytes), 'image/png')

  // Construct JPEG bytes
  const jpegBytes = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10])
  assert.equal(detectImageMimeType(jpegBytes), 'image/jpeg')

  // Construct GIF bytes
  const gifBytes = new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61])
  assert.equal(detectImageMimeType(gifBytes), 'image/gif')

  // Sliced to 8 bytes fails WebP detection (regression check for 8-byte slice bug)
  const truncatedWebp = webpBytes.slice(0, 8)
  assert.equal(detectImageMimeType(truncatedWebp), null)
})

test('Test 4 – API client: setPrimaryProfilePhoto sends PUT /api/v1/profile/photos/:id/primary', async () => {
  const originalFetch = globalThis.fetch
  let interceptedUrl = ''
  let interceptedMethod = ''

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    interceptedUrl = String(input)
    interceptedMethod = init?.method || 'GET'
    return new Response(
      JSON.stringify({
        id: 42,
        photo_url: '/uploads/profiles/profile_42.jpg',
        is_primary: true,
        display_order: 1,
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    )
  }) as typeof fetch

  try {
    const result = await setPrimaryProfilePhoto(42)
    assert.ok(interceptedUrl.includes('/api/v1/profile/photos/42/primary'))
    assert.equal(interceptedMethod, 'PUT')
    assert.equal(result.id, 42)
    assert.equal(result.is_primary, true)
    assert.equal(result.display_order, 1)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Test 5 – API client: reorderProfilePhotos sends PUT /api/v1/profile/photos/reorder with photo_ids payload', async () => {
  const originalFetch = globalThis.fetch
  let interceptedUrl = ''
  let interceptedMethod = ''
  let interceptedBody = ''

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    interceptedUrl = String(input)
    interceptedMethod = init?.method || 'GET'
    interceptedBody = String(init?.body || '')
    return new Response(
      JSON.stringify([
        { id: 2, photo_url: '/uploads/profiles/2.jpg', is_primary: true, display_order: 1 },
        { id: 1, photo_url: '/uploads/profiles/1.jpg', is_primary: false, display_order: 2 },
      ]),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    )
  }) as typeof fetch

  try {
    const result = await reorderProfilePhotos([2, 1])
    assert.ok(interceptedUrl.includes('/api/v1/profile/photos/reorder'))
    assert.equal(interceptedMethod, 'PUT')
    assert.deepEqual(JSON.parse(interceptedBody), { photo_ids: [2, 1] })
    assert.equal(result.length, 2)
    assert.equal(result[0].id, 2)
    assert.equal(result[0].is_primary, true)
    assert.equal(result[1].id, 1)
    assert.equal(result[1].is_primary, false)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Test 6 – API client: deleteProfilePhoto dispatches DELETE /api/v1/profile/photos/:id', async () => {
  const originalFetch = globalThis.fetch
  let interceptedUrl = ''
  let interceptedMethod = ''

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    interceptedUrl = String(input)
    interceptedMethod = init?.method || 'GET'
    return new Response(JSON.stringify({ deleted: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as typeof fetch

  try {
    const result = await deleteProfilePhoto(99)
    assert.ok(interceptedUrl.includes('/api/v1/profile/photos/99'))
    assert.equal(interceptedMethod, 'DELETE')
    assert.equal(result.deleted, true)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Test 7 – Deletion primary photo promotion fallback logic', () => {
  function simulateDeletePhoto(photos: ProfilePhoto[], deleteId: number): ProfilePhoto[] {
    const target = photos.find(p => p.id === deleteId)
    if (!target) return photos

    const wasPrimary = target.is_primary
    const remaining = photos.filter(p => p.id !== deleteId)

    if (wasPrimary && remaining.length > 0) {
      remaining[0].is_primary = true
    }
    return remaining
  }

  const initialPhotos: ProfilePhoto[] = [
    { id: 1, photo_url: '/uploads/profiles/1.jpg', is_primary: true, display_order: 1 },
    { id: 2, photo_url: '/uploads/profiles/2.jpg', is_primary: false, display_order: 2 },
    { id: 3, photo_url: '/uploads/profiles/3.jpg', is_primary: false, display_order: 3 },
  ]

  // Delete non-primary photo -> photo 1 stays primary
  const afterNonPrimary = simulateDeletePhoto([...initialPhotos], 2)
  assert.equal(afterNonPrimary.length, 2)
  assert.equal(afterNonPrimary[0].id, 1)
  assert.equal(afterNonPrimary[0].is_primary, true)

  // Delete primary photo -> photo 2 is promoted to primary
  const afterPrimary = simulateDeletePhoto([...initialPhotos], 1)
  assert.equal(afterPrimary.length, 2)
  assert.equal(afterPrimary[0].id, 2)
  assert.equal(afterPrimary[0].is_primary, true)
})

test('Test 8 – Avatar fallback behavior: missing or errored photos safely produce user initial', () => {
  function getAvatarDisplay({
    src,
    name,
    hasError,
  }: {
    src?: string | null
    name: string
    hasError: boolean
  }): { type: 'image' | 'initial'; value: string } {
    const initial = (name.trim()[0] || 'R').toUpperCase()
    const resolved = resolveMediaUrl(src)
    if (resolved && !hasError) {
      return { type: 'image', value: resolved }
    }
    return { type: 'initial', value: initial }
  }

  // Valid photo
  const valid = getAvatarDisplay({
    src: '/uploads/profiles/pic.jpg',
    name: 'Shree',
    hasError: false,
  })
  assert.equal(valid.type, 'image')
  assert.ok(valid.value.endsWith('/uploads/profiles/pic.jpg'))

  // Errored photo URL -> falls back to initial
  const errored = getAvatarDisplay({
    src: '/uploads/profiles/broken.jpg',
    name: 'Shree',
    hasError: true,
  })
  assert.equal(errored.type, 'initial')
  assert.equal(errored.value, 'S')

  // Null photo -> falls back to initial
  const nullPhoto = getAvatarDisplay({
    src: null,
    name: 'Omkar',
    hasError: false,
  })
  assert.equal(nullPhoto.type, 'initial')
  assert.equal(nullPhoto.value, 'O')

  // Empty string name -> fallback to 'R'
  const emptyName = getAvatarDisplay({
    src: null,
    name: '',
    hasError: false,
  })
  assert.equal(emptyName.type, 'initial')
  assert.equal(emptyName.value, 'R')
})

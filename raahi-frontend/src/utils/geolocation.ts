/**
 * Geolocation utility for Raahi dating platform.
 *
 * Privacy Guarantees:
 * 1. User permission is requested only upon an explicit user action (e.g. clicking "Detect Location").
 * 2. Exact GPS coordinates are used exclusively for approximate city/region resolution.
 * 3. Exact coordinates are NEVER stored on backend profiles or broadcast to other members.
 * 4. Manual city input is always supported as an alternative fallback.
 */

export interface GeolocationResult {
  city?: string
  latitude?: number
  longitude?: number
  error?: string
  permissionDenied?: boolean
  code?: 'PERMISSION_DENIED' | 'POSITION_UNAVAILABLE' | 'TIMEOUT' | 'UNSUPPORTED' | 'NETWORK_ERROR'
}

/**
 * Request user's current city via browser geolocation and approximate reverse geocoding.
 */
export async function requestCurrentLocation(): Promise<GeolocationResult> {
  if (typeof navigator === 'undefined' || !navigator?.geolocation) {
    return {
      error: 'Geolocation is not supported by your browser. Please enter your city manually.',
      code: 'UNSUPPORTED',
    }
  }

  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords
        try {
          // Approximate reverse geocoding using BigDataCloud's free client-side API
          const response = await fetch(
            `https://api.bigdatacloud.net/data/reverse-geocode-client?latitude=${latitude}&longitude=${longitude}&localityLanguage=en`
          )
          if (response.ok) {
            const data = await response.json()
            const detectedCity = data.city || data.locality || data.principalSubdivision || 'Nearby'
            resolve({
              city: detectedCity,
              latitude,
              longitude,
            })
            return
          }
        } catch {
          // If geocoding API is unreachable, return approximate fallback
        }

        resolve({
          city: 'Current Location',
          latitude,
          longitude,
        })
      },
      (geoError) => {
        if (geoError.code === geoError.PERMISSION_DENIED) {
          resolve({
            error: 'Location permission was denied. You can enter your city manually.',
            permissionDenied: true,
            code: 'PERMISSION_DENIED',
          })
        } else if (geoError.code === geoError.POSITION_UNAVAILABLE) {
          resolve({
            error: 'Location information is unavailable. Please enter your city manually.',
            code: 'POSITION_UNAVAILABLE',
          })
        } else if (geoError.code === geoError.TIMEOUT) {
          resolve({
            error: 'Location request timed out. Please enter your city manually.',
            code: 'TIMEOUT',
          })
        } else {
          resolve({
            error: 'Could not retrieve location. Please enter your city manually.',
            code: 'NETWORK_ERROR',
          })
        }
      },
      {
        timeout: 10000,
        enableHighAccuracy: false,
        maximumAge: 60000,
      }
    )
  })
}

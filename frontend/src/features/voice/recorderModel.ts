/** Pure helpers for the hold-to-record button (no browser state). */

/** Presses shorter than this are discarded (an accidental tap, not a note). */
export const MIN_RECORDING_MS = 1_000
/** Recording stops by itself after 10 minutes (and is kept). */
export const MAX_RECORDING_MS = 10 * 60_000

/** Preferred first (PRD 6.5: webm/opus); Safari only has mp4. */
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'] as const

/** The first candidate the browser can record, or undefined (let the browser choose). */
export function pickMimeType(isTypeSupported: ((type: string) => boolean) | undefined): string | undefined {
  if (!isTypeSupported) return undefined
  return MIME_CANDIDATES.find((type) => {
    try {
      return isTypeSupported(type)
    } catch {
      return false
    }
  })
}

const FALLBACK_MIME = 'audio/webm'

/** "audio/webm;codecs=opus" → "audio/webm"; empty → audio/webm (what Chrome records). */
export function baseMimeType(type: string | undefined): string {
  const base = (type ?? '').split(';')[0]?.trim().toLowerCase() ?? ''
  return base === '' ? FALLBACK_MIME : base
}

export type MicErrorKind = 'denied' | 'no_mic' | 'unsupported' | 'other'

/** getUserMedia rejections → what the user can do about it. */
export function micErrorKind(error: unknown): MicErrorKind {
  const name = error instanceof Error || error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') return 'denied'
  if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'DevicesNotFoundError') return 'no_mic'
  return 'other'
}

/** 75_400 ms → "1:15". */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

/** Duration sent with the recording, in seconds with 0.1 s precision. */
export function durationSeconds(ms: number): number {
  return Math.round(Math.max(0, ms) / 100) / 10
}

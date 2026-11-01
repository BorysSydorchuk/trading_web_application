import { uk } from '@/i18n/uk'

type KnownSyncError = Exclude<keyof typeof uk.sync.errors, 'unknown'>

/** Worker error code → short Ukrainian text (`sync.errors.<code>`, fallback `unknown`). */
export function syncErrorText(code: string | null): string {
  if (code !== null && code !== 'unknown' && Object.hasOwn(uk.sync.errors, code)) {
    return uk.sync.errors[code as KnownSyncError]
  }
  return uk.sync.errors.unknown
}

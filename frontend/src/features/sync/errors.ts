import type { AccountPlatform } from '@/features/accounts/types'
import { uk } from '@/i18n/uk'

type KnownSyncError = Exclude<keyof typeof uk.sync.errors, 'unknown'>

const ctraderTexts: Readonly<Record<string, string>> = uk.ctrader.errors

/**
 * Worker error code → short Ukrainian text; a code never shows raw (fallback `unknown`).
 * `timeout` and `internal_error` are shared by both platforms, so the account's platform picks the text.
 * `platform` is undefined while it is not known: then `timeout` names neither platform.
 */
export function syncErrorText(code: string | null, platform?: AccountPlatform): string {
  if (code === null || code === 'unknown') return uk.sync.errors.unknown
  if (platform === 'ctrader' && Object.hasOwn(ctraderTexts, code)) return ctraderTexts[code] ?? uk.sync.errors.unknown
  if (platform === undefined && code === 'timeout') return uk.sync.timeoutUnknownPlatform
  if (Object.hasOwn(uk.sync.errors, code)) return uk.sync.errors[code as KnownSyncError]
  if (Object.hasOwn(ctraderTexts, code)) return ctraderTexts[code] ?? uk.sync.errors.unknown
  return uk.sync.errors.unknown
}

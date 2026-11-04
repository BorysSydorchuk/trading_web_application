import { toast } from 'sonner'
import { isApiError, type ApiError } from '@/api/client'
import { uk, type KnownErrorCode } from '@/i18n/uk'

/** Keys of `uk.errors` that are not plain error codes. */
const NON_CODE_KEYS = new Set(['unknown', 'ai_error_kinds'])

function isKnownCode(code: string): code is KnownErrorCode {
  return !NON_CODE_KEYS.has(code) && Object.hasOwn(uk.errors, code)
}

/** `ai_error` → `errors.ai_error_kinds.<details.kind>`, falling back to `errors.ai_error` (docs/api.md). */
function aiErrorText(error: ApiError): string {
  const kind = error.details?.kind
  const kinds: Readonly<Record<string, string>> = uk.errors.ai_error_kinds
  if (typeof kind === 'string' && Object.hasOwn(kinds, kind)) return kinds[kind] ?? uk.errors.ai_error
  return uk.errors.ai_error
}

/** Maps any thrown value to readable Ukrainian text. */
export function errorText(error: unknown): string {
  if (!isApiError(error)) return uk.errors.unknown
  if (error.code === 'ai_error') return aiErrorText(error)
  if (isKnownCode(error.code)) return uk.errors[error.code]
  return uk.errors.unknown
}

/** Shows an error toast. Same error code collapses into one toast instead of stacking. */
export function showErrorToast(error: unknown): void {
  const id = isApiError(error) ? `api-error:${error.code}` : 'error:unknown'
  toast.error(errorText(error), { id })
}

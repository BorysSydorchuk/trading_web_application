import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { uk, type KnownErrorCode } from '@/i18n/uk'

function isKnownCode(code: string): code is KnownErrorCode {
  return code !== 'unknown' && Object.hasOwn(uk.errors, code)
}

/** Maps any thrown value to readable Ukrainian text. */
export function errorText(error: unknown): string {
  if (isApiError(error) && isKnownCode(error.code)) return uk.errors[error.code]
  return uk.errors.unknown
}

/** Shows an error toast. Same error code collapses into one toast instead of stacking. */
export function showErrorToast(error: unknown): void {
  const id = isApiError(error) ? `api-error:${error.code}` : 'error:unknown'
  toast.error(errorText(error), { id })
  console.error(error)
}

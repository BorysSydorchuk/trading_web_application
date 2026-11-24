/** The one-time result the OAuth callback puts in the /settings query string (docs/api.md). */
const SUCCESS_PARAM = 'ctrader'
const ERROR_PARAM = 'ctrader_error'
const SUCCESS_VALUE = 'connected'

export type OauthReturn = { ok: true } | { ok: false; code: string }

/** null = this URL is not a return from cTrader. An error wins over a success value. */
export function readOauthReturn(params: URLSearchParams): OauthReturn | null {
  const code = params.get(ERROR_PARAM)
  if (code !== null) return { ok: false, code }
  const value = params.get(SUCCESS_PARAM)
  if (value === null) return null
  return value === SUCCESS_VALUE ? { ok: true } : { ok: false, code: 'unknown' }
}

/** A copy without the cTrader parameters; other parameters stay. */
export function cleanedOauthParams(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params)
  next.delete(SUCCESS_PARAM)
  next.delete(ERROR_PARAM)
  return next
}

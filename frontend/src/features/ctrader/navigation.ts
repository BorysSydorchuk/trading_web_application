/** Full-page navigation to the cTrader sign-in (a separate module so tests can replace it). */
export function navigateToAuthorizeUrl(url: string): void {
  window.location.assign(url)
}

/** Only an https address may be opened: a `javascript:` value must never reach `location.assign`. */
export function isSafeAuthorizeUrl(url: string): boolean {
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

/** Open position display rules (M8-10b): time in trade, missing live values, usable R scale. */
import { uk } from '@/i18n/uk'
import { brusselsHourMinute, minutesBetween, splitDuration } from './dates'
import type { HomePosition } from './types'

const t = uk.home.positions

/** "58 хв", "2 год 5 хв", "1 д 3 год". */
export function timeInTrade(openTime: string, now: string): string {
  const { days, hours, minutes } = splitDuration(minutesBetween(openTime, now))
  if (days > 0) return t.ageDays(days, hours)
  if (hours > 0) return t.ageHours(hours, minutes)
  return t.ageMinutes(minutes)
}

/** Fresh live values: the API sends a price or a P&L only from a fresh snapshot (cTrader has no price). */
export function hasLiveValues(position: Pick<HomePosition, 'current_price' | 'pnl'>): boolean {
  return position.current_price !== null || position.pnl !== null
}

/**
 * Live values missing: the platform no longer reports the position («Не вдалося підтвердити
 * закриття»), no snapshot («ціна недоступна») or an old one («дані застаріли HH:MM»).
 */
export function liveNote(position: Pick<HomePosition, 'current_price' | 'pnl' | 'price_time' | 'close_unconfirmed'>): string | null {
  if (position.close_unconfirmed) return t.closeUnconfirmed
  if (hasLiveValues(position)) return null
  return position.price_time === null ? t.priceUnavailable : t.stale(brusselsHourMinute(position.price_time))
}

/**
 * The R scale needs a usable initial SL. The API returns r_now / tp_r null when the SL is missing or
 * not on the losing side; a fresh price with r_now null therefore means "no usable SL".
 */
export function hasRScale(position: HomePosition): boolean {
  if (position.initial_sl === null) return false
  return position.r_now !== null || position.tp_r !== null || position.current_price === null
}

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

/** Live values missing: no snapshot («ціна недоступна») or an old one («дані застаріли HH:MM»). */
export function liveNote(position: Pick<HomePosition, 'current_price' | 'price_time'>): string | null {
  if (position.current_price !== null) return null
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

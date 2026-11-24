import { Loader2 } from 'lucide-react'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels, formatTimeBrussels } from '@/lib/time'
import { formatMoney, formatVolume, marginFailureText } from './format'
import type { MarginInfo } from './types'
import type { LiveMargin } from './useLiveMargin'

const t = uk.calculator.result

function money(amount: string, currency: string | null) {
  return (
    <span className="num font-medium">
      {formatMoney(amount)} {currency}
    </span>
  )
}

function liveTime(at: string | null): string {
  if (at === null) return t.marginLiveNoTime
  const date = new Date(at)
  return Number.isNaN(date.getTime()) ? t.marginLiveNoTime : t.marginLive(formatTimeBrussels(date))
}

/** Cached estimate from the calculate response, or «маржа недоступна». */
function Estimate({ margin, digitsPrice }: { margin: MarginInfo; digitsPrice: (value: string) => string }) {
  if (margin.source !== 'cached_estimate' || margin.amount === null) {
    return <span className="text-ink-muted">{t.marginUnavailable}</span>
  }
  const date = margin.calculated_at === null ? uk.common.empty : formatDateTimeBrussels(margin.calculated_at)
  const price = margin.sample_price === null ? uk.common.empty : digitsPrice(margin.sample_price)
  return (
    <span className="flex flex-col items-end gap-0.5">
      {money(margin.amount, margin.currency)}
      <span className="text-right text-xs text-ink-muted">
        {t.marginEstimate(date, price, formatVolume(margin.sample_volume))}
      </span>
    </span>
  )
}

interface MarginValueProps {
  live: LiveMargin | null
  cached: MarginInfo
  digitsPrice: (value: string) => string
}

/** Live MT5 margin while/after polling; on failure (or for cTrader) the labelled cached estimate. */
export function MarginValue({ live, cached, digitsPrice }: MarginValueProps) {
  if (live?.state === 'unsupported') {
    return (
      <span className="flex flex-col items-end gap-0.5">
        <Estimate margin={cached} digitsPrice={digitsPrice} />
        <span className="text-right text-xs text-ink-muted">{t.marginCtrader}</span>
      </span>
    )
  }
  if (live === null || live.state === 'pending') {
    return (
      <span role="status" className="inline-flex items-center gap-1.5 text-ink-muted">
        <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
        {t.marginPending}
      </span>
    )
  }
  if (live.state === 'done') {
    return (
      <span className="flex flex-col items-end gap-0.5">
        {money(live.amount, live.currency)}
        <span className="text-xs text-ink-muted">{liveTime(live.at)}</span>
      </span>
    )
  }
  return (
    <span className="flex flex-col items-end gap-0.5">
      <Estimate margin={cached} digitsPrice={digitsPrice} />
      <span className="text-right text-xs text-ink-muted">{marginFailureText(live.reason, live.code)}</span>
    </span>
  )
}

import { useId } from 'react'
import { Link } from 'react-router'
import { Pill } from '@/components/studio/Pill'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { INBOX_POLL_MS } from '@/features/inbox/api'
import { useTrades } from '@/features/trades/api'
import { describePath } from '@/features/trades/links'
import type { TradeQuery } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { formatR } from '@/lib/displayFormat'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { brusselsDayMonth } from './dates'
import { signTone } from './heroSeries'

const t = uk.home.needs
/** Tiles on Home; the rest is one click away in the Journal («+N у журналі»). */
export const HOME_NEEDS_DESCRIPTION_TILES = 5
export const JOURNAL_NEEDS_DESCRIPTION = '/journal?status=needs_description&excluded=hide'
/** M8-15 rule (same as the inbox «Без опису» count): needs_description, counted in statistics,
 * active (not archived) accounts, newest closed first. */
const QUERY: TradeQuery = {
  status: ['needs_description'],
  excluded: false,
  archived: false,
  sort: 'close_time',
  order: 'desc',
  limit: HOME_NEEDS_DESCRIPTION_TILES,
  offset: 0,
}

const TILE = 'lift flex flex-col gap-0.5 rounded-2xl border border-line p-3.5 text-ink outline-none focus-visible:ring-[3px] focus-visible:ring-ring'

/** «Потрібен опис»: up to 5 trade tiles + «+N у журналі». */
export function NeedsDescriptionTiles() {
  const id = useId()
  const query = useTrades(QUERY, { refetchInterval: INBOX_POLL_MS })
  const items = query.data?.items ?? []
  const total = query.data?.total ?? 0
  const rest = total - items.length
  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-3">
      <SectionHeader id={`${id}-title`} title={t.title}>
        {total > 0 && (
          <Pill tone="loss" mono size="md" aria-label={t.count(total)} className="py-0.5">
            {total}
          </Pill>
        )}
      </SectionHeader>
      {query.isPending ? (
        <p role="status" className="text-xs text-ink-muted">{t.loading}</p>
      ) : query.isError ? (
        <p role="alert" className="rounded-card border border-dashed border-input px-4 py-3 text-sm text-destructive">
          {t.error} {errorText(query.error)}
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-card border border-dashed border-input px-4 py-3 text-sm text-ink-muted">{t.empty}</p>
      ) : (
        <ul className="grid grid-cols-6 gap-3">
          {items.map((trade) => {
            const tone = signTone(trade.r_multiple ?? trade.net_pnl)
            const date = trade.close_time ? brusselsDayMonth(trade.close_time) : uk.common.empty
            return (
              <li key={trade.id} className="flex">
                <Link
                  to={describePath(trade.id)}
                  aria-label={t.tileLabel(trade.symbol, date)}
                  className={cn(
                    TILE,
                    'w-full bg-linear-160 to-lavender-soft',
                    tone === 'loss' ? 'from-loss-wash' : tone === 'profit' ? 'from-profit-wash' : 'from-track',
                  )}
                >
                  <span className="flex items-center justify-between gap-1">
                    <span className="type-symbol truncate text-base">{trade.symbol}</span>
                    <span
                      className={cn(
                        'num rounded-lg bg-surface px-1.5 py-0.5 text-xs font-semibold',
                        tone === 'loss' ? 'text-loss' : tone === 'profit' ? 'text-profit' : 'text-ink',
                      )}
                    >
                      {formatR(trade.r_multiple, 'overview')}
                    </span>
                  </span>
                  <span className="num text-xs text-ink-muted">{date}</span>
                  <span className="mt-2 rounded-[10px] bg-surface py-1.5 text-center text-[13px] font-semibold text-lavender">{t.describe}</span>
                </Link>
              </li>
            )
          })}
          {rest > 0 && (
            <li className="flex">
              <Link
                to={JOURNAL_NEEDS_DESCRIPTION}
                aria-label={t.moreLabel(rest)}
                className="lift flex w-full flex-col items-center justify-center gap-1 rounded-2xl border-[1.5px] border-dashed border-input p-3.5 text-ink-muted outline-none focus-visible:ring-[3px] focus-visible:ring-ring"
              >
                <span className="type-symbol text-[22px] text-ink">{t.more(rest)}</span>
                <span className="text-xs">{t.moreText}</span>
              </Link>
            </li>
          )}
        </ul>
      )}
    </section>
  )
}

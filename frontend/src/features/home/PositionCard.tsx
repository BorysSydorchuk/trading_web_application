import { Link } from 'react-router'
import { Pill } from '@/components/studio/Pill'
import { describePath } from '@/features/trades/links'
import { uk } from '@/i18n/uk'
import { formatLots, formatPct, formatPrice, formatR } from '@/lib/displayFormat'
import { cn } from '@/lib/utils'
import { ladderGeometry } from './chartMath'
import { signTone } from './heroSeries'
import { hasLiveValues, hasRScale, liveNote, timeInTrade } from './positionModel'
import type { HomePosition } from './types'

const t = uk.home.positions

const num = (value: string | null) => (value === null ? null : Number(value))
/** MAE / MFE are magnitudes (>= 0): shown without a sign, e.g. "0.2R". */
const unsignedR = (value: string | null) =>
  formatR(value === null ? null : value.replace(/^[+-]/, ''), 'overview').replace(/^\+/, '')

function Ladder({ position }: { position: HomePosition }) {
  const g = ladderGeometry({ tpR: num(position.tp_r), rNow: num(position.r_now), maeR: num(position.mae_r), mfeR: num(position.mfe_r) })
  const tpText = position.tp_r === null ? t.noTp : formatR(position.tp_r, 'overview')
  const price = position.current_price
  const nowText = price === null ? (liveNote(position) ?? uk.common.empty) : formatPrice(price, 'overview')
  const good = signTone(position.r_now) !== 'loss'
  return (
    <div role="img" aria-label={t.ladder(position.symbol, nowText, tpText)} data-testid="position-ladder" className="relative mt-2.5 h-[66px]">
      {g.now !== null && price !== null && (
        <div
          data-testid="position-now-tag"
          className="num absolute top-0 -translate-x-1/2 rounded-lg border border-line bg-surface px-2 py-px text-[11px] font-semibold whitespace-nowrap text-ink"
          style={{ left: `${g.now}%` }}
        >
          {formatPrice(price, 'overview')}
        </div>
      )}
      <div className="absolute inset-x-0 top-[30px] h-2.5 rounded-[5px] bg-track" />
      <div
        data-testid="position-loss-track"
        className="absolute top-[30px] left-0 h-2.5 rounded-l-[5px] bg-linear-90 from-loss-mid/70 to-loss-wash"
        style={{ width: `${g.entry}%` }}
      />
      <div
        className="absolute top-[30px] right-0 h-2.5 rounded-r-[5px] bg-linear-90 from-profit-wash to-profit-mid/80"
        style={{ left: `${g.entry}%` }}
      />
      {g.bandLeft !== null && g.bandWidth !== null && (
        <div
          data-testid="position-band"
          className="absolute top-[33px] h-1 rounded-[2px] bg-lavender-mid/60"
          style={{ left: `${g.bandLeft}%`, width: `${g.bandWidth}%` }}
        />
      )}
      <div className="absolute top-[26px] h-[18px] w-0.5 rounded-[1px] bg-faint" style={{ left: `${g.entry}%` }} />
      {g.now !== null && (
        <div
          data-testid="position-now-dot"
          className={cn(
            'absolute top-[25px] size-5 -translate-x-1/2 rounded-full border-4 border-surface',
            'shadow-[0_0_0_1px_var(--tj-border),0_4px_10px_-3px_rgb(40_40_60/0.35)]',
            good ? 'bg-profit-strong' : 'bg-loss-strong',
          )}
          style={{ left: `${g.now}%` }}
        />
      )}
      <span className="num absolute top-12 left-0 text-[11px] text-loss">{t.sl}</span>
      <span className="num absolute top-12 -translate-x-1/2 text-[11px] text-ink-muted" style={{ left: `${g.entry}%` }}>
        {t.entry}
      </span>
      <span className={cn('num absolute top-12 right-0 text-[11px]', position.tp_r === null ? 'text-ink-muted' : 'text-profit')}>
        {tpText}
      </span>
    </div>
  )
}

function LiveValues({ position }: { position: HomePosition }) {
  const note = liveNote(position)
  if (note !== null) {
    // A system state (no or old snapshot): warning tone, never P&L colours.
    return (
      <Pill tone="warning" data-testid="position-live-note">
        {note}
      </Pill>
    )
  }
  const tone = signTone(position.pnl)
  return (
    <>
      <p className={cn('num text-2xl font-semibold', tone === 'loss' ? 'text-loss' : tone === 'profit' ? 'text-profit' : 'text-ink')}>
        {formatPct(position.pnl_pct, 'overview', { signed: true })}
      </p>
      <p className="num text-xs text-ink-muted">{formatR(position.r_now, 'overview')}</p>
    </>
  )
}

function Excursions({ position }: { position: HomePosition }) {
  return (
    <>
      <span aria-label={t.maeLabel(unsignedR(position.mae_r))} className="num rounded-[10px] bg-loss-wash px-2.5 py-1 text-xs font-semibold text-loss">
        {t.mae(unsignedR(position.mae_r))}
      </span>
      <span aria-label={t.mfeLabel(unsignedR(position.mfe_r))} className="num rounded-[10px] bg-profit-wash px-2.5 py-1 text-xs font-semibold text-profit">
        {t.mfe(unsignedR(position.mfe_r))}
      </span>
    </>
  )
}

/** One open position (mockup card): P&L and R, SL → entry → TP ladder, MAE / MFE, description state. */
export function PositionCard({ position, now }: { position: HomePosition; now: string }) {
  const tone = hasLiveValues(position) && !position.close_unconfirmed ? signTone(position.pnl) : 'neutral'
  const side = position.direction.toLowerCase()
  return (
    <article
      aria-label={position.symbol}
      className={cn(
        'lift flex flex-col rounded-card border border-line bg-surface px-[18px] pt-[18px] pb-4',
        tone === 'profit' && 'bg-linear-180 from-profit-wash to-surface to-46%',
        tone === 'loss' && 'bg-linear-180 from-loss-wash to-surface to-46%',
      )}
    >
      <div className="flex items-start justify-between gap-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="type-symbol text-[22px]">{position.symbol}</span>
            {/* Side and description state are not P&L: neutral pills (green/red only for P&L values). */}
            <Pill tone="neutral" className="text-[11px] tracking-[0.04em] uppercase">
              {t.sides[side] ?? position.direction}
            </Pill>
          </div>
          <p className="mt-0.5 text-xs text-ink-muted">
            {t.meta(formatLots(position.volume), position.account_name, timeInTrade(position.open_time, now))}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <LiveValues position={position} />
        </div>
      </div>
      {position.close_unconfirmed ? (
        // Never a live card for a position MT5 does not report (owner bug 2026-11-20).
        <p data-testid="position-close-unconfirmed" className="mt-3 text-xs text-ink-muted">
          {t.closeUnconfirmedHint}
        </p>
      ) : !hasRScale(position) ? (
        <p className="mt-3 text-xs text-ink-muted">{t.noSl}</p>
      ) : (
        <Ladder position={position} />
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        {!position.close_unconfirmed && <Excursions position={position} />}
        <span className="flex-1" />
        <Pill tone="neutral" data-testid="position-described" className="rounded-[10px] px-2.5 py-1">
          {position.described ? t.described : t.notDescribed}
        </Pill>
      </div>
      <Link
        to={describePath(position.trade_id)}
        aria-label={t.describeLabel(position.symbol)}
        className="mt-3 rounded-xl bg-lavender-soft px-3.5 py-2.5 text-center text-[13px] font-semibold text-lavender outline-none hover:bg-lavender-button focus-visible:ring-[3px] focus-visible:ring-ring"
      >
        {t.describe}
      </Link>
    </article>
  )
}

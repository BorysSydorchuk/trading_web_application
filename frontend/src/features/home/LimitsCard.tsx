import { useId } from 'react'
import { Card } from '@/components/studio/Card'
import { Tile } from '@/components/studio/Tile'
import { uk } from '@/i18n/uk'
import { formatPct, formatUsd } from '@/lib/displayFormat'
import { cn } from '@/lib/utils'
import { limitBarGeometry } from './chartMath'
import { signTone } from './heroSeries'
import type { HomeLimits, LimitPeriod } from './types'

const t = uk.home.limits
const pctSigned = (v: string | null) => formatPct(v, 'overview', { signed: true })
const pctPlain = (v: string | null) => formatPct(v, 'overview')

const num = (value: string | null) => (value === null ? null : Number(value))

function LimitRow({ label, period }: { label: string; period: LimitPeriod }) {
  // pct is null without an account size: the bar shows only the limits, the value «—».
  const current = period.pct === null ? 0 : Number(period.pct)
  const loss = num(period.loss_pct)
  const profit = num(period.profit_pct)
  const g = limitBarGeometry(Number.isFinite(current) ? current : 0, loss, profit)
  const tone = signTone(period.pct)
  const value = pctSigned(period.pct)
  const low = period.loss_pct === null ? t.noLimit : pctPlain(period.loss_pct)
  const high = period.profit_pct === null ? t.noLimit : pctSigned(period.profit_pct)
  return (
    <div className="flex flex-col gap-2 border-b border-divider py-3 last:border-b-0">
      <div className="flex items-baseline justify-between">
        <span className="font-semibold">{label}</span>
        <span className={cn('num text-base font-semibold', tone === 'loss' ? 'text-loss' : tone === 'profit' ? 'text-profit' : 'text-ink')}>{value}</span>
      </div>
      <div role="img" aria-label={t.barLabel(label, value, low, high)} data-testid="limit-bar" className="relative h-3">
        <div className="absolute inset-0 rounded-md bg-track" />
        {g.lossZone > 0 && (
          <div
            data-testid="limit-loss-zone"
            className="absolute inset-y-0 left-0 rounded-l-md bg-[repeating-linear-gradient(135deg,var(--tj-loss-wash)_0_6px,var(--tj-loss-light)_6px_12px)]"
            style={{ width: `${g.lossZone}%` }}
          />
        )}
        <div
          data-testid="limit-fill"
          className={cn(
            'absolute inset-y-0',
            period.pct === null && 'hidden',
            current >= 0 ? 'rounded-r-md bg-linear-90 from-profit-light to-profit-mid' : 'rounded-l-md bg-linear-270 from-loss-light to-loss-mid',
          )}
          style={{ left: `${g.fillLeft}%`, width: `${g.fillWidth}%` }}
        />
        <div data-testid="limit-zero" className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-[1px] bg-faint" style={{ left: `${g.zero}%` }} />
      </div>
      <div className="num flex justify-between text-[11px]">
        <span className={period.loss_pct === null ? 'text-ink-muted' : 'text-loss'}>{low}</span>
        <span className={period.profit_pct === null ? 'text-ink-muted' : 'text-profit'}>{high}</span>
      </div>
    </div>
  )
}

/** Exact figures, to compare with the trading platform; the last known ones when stale. */
function BalanceRow({ limits }: { limits: HomeLimits }) {
  if (limits.balance === null && limits.equity === null) return null
  const money = (value: string | null) => (value === null ? uk.common.empty : `${formatUsd(value, 'exact')} ${limits.currency}`)
  return (
    <div data-testid="limits-balance" className="flex flex-col gap-1 border-b border-divider py-3">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-ink-muted">{t.balance}</span>
        <span className="num font-semibold">{money(limits.balance)}</span>
      </div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-ink-muted">{t.equity}</span>
        <span className="num font-semibold">{money(limits.equity)}</span>
      </div>
      {!limits.balance_fresh && <p data-testid="limits-balance-stale" className="text-[11px] text-ink-muted">{t.balanceStale}</p>}
    </div>
  )
}

export interface LimitsCardProps {
  /** undefined while `GET /api/home` loads (or failed); null when there is no account. */
  limits: HomeLimits | null | undefined
  /** First load failed: readable reason shown in the card (e.g. mixed currencies). */
  error?: string | null
  /** Number of active accounts: with more than one and «Усі рахунки» the card notes why this account. */
  accountCount: number
  /** null = all accounts: the server picks the one closest to its daily stop (account chip in the header). */
  accountId: number | null
}

/** «Ліміти»: day / week / month bars of one account, trades this week and the room to the daily stop. */
export function LimitsCard({ limits, error = null, accountCount, accountId }: LimitsCardProps) {
  const id = useId()
  return (
    <Card lift aria-labelledby={`${id}-title`} className="flex flex-col gap-1 rounded-[22px] px-[22px] pt-[22px] pb-[18px]">
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="type-card-title">
          {t.title}
        </h2>
        {limits && (
          <p className="text-xs text-ink-muted">
            {limits.account_name}
            {accountId === null && accountCount > 1 && ` · ${t.closest}`}
          </p>
        )}
      </div>
      {limits === undefined && error !== null ? (
        <p className="py-6 text-sm text-destructive">{error}</p>
      ) : limits === undefined ? (
        <p role="status" className="py-6 text-sm text-ink-muted">{uk.dashboard.loading}</p>
      ) : limits === null ? (
        <p className="py-6 text-sm text-ink-muted">{t.empty}</p>
      ) : (
        <>
          <BalanceRow limits={limits} />
          <LimitRow label={t.day} period={limits.day} />
          <LimitRow label={t.week} period={limits.week} />
          <LimitRow label={t.month} period={limits.month} />
          <div className="flex gap-2.5 pt-3">
            <Tile tone="accent" className="flex-1">
              <p className="text-[11px] text-ink-muted">{t.trades}</p>
              <p className="num text-lg font-semibold">
                {limits.trades_week}
                {limits.max_trades_week !== null && <span className="text-[13px] text-ink-muted">{t.tradesOf(limits.max_trades_week)}</span>}
              </p>
            </Tile>
            <Tile tone={limits.to_daily_stop_pct !== null && Number(limits.to_daily_stop_pct) <= 0 ? 'loss' : 'profit'} className="flex-1">
              <p className="text-[11px] text-ink-muted">{t.toStop}</p>
              <p className="num text-lg font-semibold">{pctPlain(limits.to_daily_stop_pct)}</p>
            </Tile>
          </div>
        </>
      )}
    </Card>
  )
}

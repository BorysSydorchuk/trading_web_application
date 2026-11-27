import { useId } from 'react'
import { Card } from '@/components/studio/Card'
import { Tile } from '@/components/studio/Tile'
import { uk } from '@/i18n/uk'
import { verifyItemText } from '@/features/accounts/firmRules'
import { formatPct } from '@/lib/displayFormat'
import { floorDecimal } from '@/lib/decimal'
import { formatHmBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { limitBarGeometry } from './chartMath'
import { signTone } from './heroSeries'
import type { FirmAlert, FirmDay, HomeLimits, LimitPeriod } from './types'

const t = uk.home.limits
const pctSigned = (v: string | null) => formatPct(v, 'overview', { signed: true })
const pctPlain = (v: string | null) => formatPct(v, 'overview')

const num = (value: string | null) => (value === null ? null : Number(value))

function toneClass(pct: string | null): string {
  const tone = signTone(pct)
  return tone === 'loss' ? 'text-loss' : tone === 'profit' ? 'text-profit' : 'text-ink'
}

interface LimitBarProps {
  /** Current %, null = unknown (no fill). */
  pct: string | null
  loss_pct: string | null
  profit_pct: string | null
  ariaLabel: string
  testId?: string
}

/** Track with the striped loss zone, the fill from zero to the current % and the zero tick. */
function LimitBar({ pct, loss_pct, profit_pct, ariaLabel, testId = 'limit-bar' }: LimitBarProps) {
  const current = pct === null ? 0 : Number(pct)
  const g = limitBarGeometry(Number.isFinite(current) ? current : 0, num(loss_pct), num(profit_pct))
  return (
    <div role="img" aria-label={ariaLabel} data-testid={testId} className="relative h-3">
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
          pct === null && 'hidden',
          current >= 0 ? 'rounded-r-md bg-linear-90 from-profit-light to-profit-mid' : 'rounded-l-md bg-linear-270 from-loss-light to-loss-mid',
        )}
        style={{ left: `${g.fillLeft}%`, width: `${g.fillWidth}%` }}
      />
      <div data-testid="limit-zero" className="absolute -inset-y-1 w-0.5 -translate-x-1/2 rounded-[1px] bg-faint" style={{ left: `${g.zero}%` }} />
    </div>
  )
}

function LimitRow({ label, period }: { label: string; period: LimitPeriod }) {
  // pct is null without an account size: the bar shows only the limits, the value «—».
  const value = pctSigned(period.pct)
  const low = period.loss_pct === null ? t.noLimit : pctPlain(period.loss_pct)
  const high = period.profit_pct === null ? t.noLimit : pctSigned(period.profit_pct)
  return (
    <div className="flex flex-col gap-2 border-b border-divider py-3 last:border-b-0">
      <div className="flex items-baseline justify-between">
        <span className="font-semibold">{label}</span>
        <span className={cn('num text-base font-semibold', toneClass(period.pct))}>{value}</span>
      </div>
      <LimitBar pct={period.pct} loss_pct={period.loss_pct} profit_pct={period.profit_pct} ariaLabel={t.barLabel(label, value, low, high)} />
      <div className="num flex justify-between text-[11px]">
        <span className={period.loss_pct === null ? 'text-ink-muted' : 'text-loss'}>{low}</span>
        <span className={period.profit_pct === null ? 'text-ink-muted' : 'text-profit'}>{high}</span>
      </div>
    </div>
  )
}

/** Overview percent precision (lib/displayFormat formatPct overview). */
const OVERVIEW_PCT_PLACES = 1

/** Room to the firm floor, never rounded up (2.75 → 2.7): the trader must not see more room than there is. */
const roomText = (v: string | null) => pctPlain(v === null ? null : floorDecimal(v, OVERVIEW_PCT_PLACES))

/** Red line under the account name: which firm limit is close and the room (rounded down). */
function firmAlertText(alert: FirmAlert): string {
  const room = alert.room_pct === null ? t.firmAlertHit : t.firmRoom(roomText(alert.room_pct))
  return t.firmAlert(t.firmAlertKinds[alert.kind], room)
}

/** «Денний ліміт фірми»: day P&L % (incl. floating) towards the firm daily floor, room and reset time. */
function FirmDayRow({ firmDay }: { firmDay: FirmDay }) {
  const value = pctSigned(firmDay.pnl_pct)
  const limit = pctPlain(firmDay.loss_pct)
  const room = firmDay.room_pct === null ? null : Number(firmDay.room_pct)
  const verify = (firmDay.to_verify ?? []).map((item) => verifyItemText(null, item))
  return (
    <div data-testid="firm-day" className="flex flex-col gap-2 border-b border-divider py-3 last:border-b-0">
      <div className="flex items-baseline justify-between">
        <span className="font-semibold">{t.firmDay}</span>
        <span className={cn('num text-base font-semibold', firmDay.breached ? 'text-loss' : toneClass(firmDay.pnl_pct))}>{value}</span>
      </div>
      <LimitBar pct={firmDay.pnl_pct} loss_pct={firmDay.loss_pct} profit_pct={null} ariaLabel={t.firmBarLabel(value, limit)} testId="firm-day-bar" />
      <div className="num flex justify-between gap-2 text-[11px]">
        <span className="text-loss">{limit}</span>
        <span className={firmDay.breached || (room !== null && room <= 0) ? 'text-loss' : 'text-ink-muted'}>
          {t.firmRoom(roomText(firmDay.room_pct))} · {t.firmDayStart(formatHmBrussels(firmDay.reset_at))}
        </span>
      </div>
      {firmDay.pnl_pct === null && <p data-testid="firm-day-no-floating" className="text-[11px] text-ink-muted">{t.firmNoFloating}</p>}
      {firmDay.breached && (
        <p data-testid="firm-day-breached" className="text-sm font-semibold text-loss">
          {t.firmBreached}
        </p>
      )}
      {verify.length > 0 && <p data-testid="firm-day-verify" className="text-[11px] text-ink-muted">{t.firmVerify(verify.join(', '))}</p>}
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
  const alert = limits?.firm_alert ?? null
  return (
    <Card
      lift
      aria-labelledby={`${id}-title`}
      data-firm-alert={alert ? alert.kind : undefined}
      className={cn('flex flex-col gap-1 rounded-[22px] px-[22px] pt-[22px] pb-[18px]', alert && 'border-loss ring-2 ring-loss/40')}
    >
      <div className="flex flex-col gap-1">
        <h2 id={`${id}-title`} className="type-card-title">
          {t.title}
        </h2>
        {limits && (
          <p className="text-xs text-ink-muted">
            {limits.account_name}
            {accountId === null && accountCount > 1 && ` · ${alert ? t.closestFirm : t.closest}`}
          </p>
        )}
        {alert && (
          <p data-testid="firm-alert" className="text-xs font-semibold text-loss">
            {firmAlertText(alert)}
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
          <LimitRow label={t.day} period={limits.day} />
          {limits.firm_day && <FirmDayRow firmDay={limits.firm_day} />}
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

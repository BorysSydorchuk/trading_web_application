/**
 * `GET /api/home?account_id=N` (docs/api.md "## M8-10b"). Money 2 dp, percents and R 4 dp, prices
 * plain decimals, all as strings; rounding is display only (lib/displayFormat, overview mode).
 */

export const SESSION_KEYS = ['london', 'premarket', 'ny', 'outside'] as const
export type SessionKey = (typeof SESSION_KEYS)[number]

export interface HomeSession {
  key: SessionKey
  entries_allowed: boolean
}

export interface BiasSymbol {
  symbol: string
  /** bullish | bearish | neutral | no_trade (features/bias/types BIAS_DIRECTIONS). */
  direction: string
}

export interface HomeBiasToday {
  /** null = no pre-London note today. */
  pre_london: BiasSymbol[] | null
  pre_ny_missing: boolean
}

/** One period of the «Ліміти» card; a null limit = the rule is off (month: no `account_limits`). */
export interface LimitPeriod {
  /** Closed P&L % of the account size; null when the account has no size > 0. */
  pct: string | null
  loss_pct: string | null
  profit_pct: string | null
}

export interface HomeLimits {
  account_id: number
  account_name: string
  currency: string
  day: LimitPeriod
  week: LimitPeriod
  month: LimitPeriod
  trades_week: number
  max_trades_week: number | null
  /** day pct − daily_stop_loss_pct; null when the daily stop is off. */
  to_daily_stop_pct: string | null
  /** Floating P&L of the open positions (money, 2 dp); null without a fresh live snapshot. */
  floating_pnl: string | null
  /** True when `floating_pnl` is counted in the day / week / month pct. */
  floating_included: boolean
}

export interface HomeKpis {
  today: { pnl: string; pct: string | null; trades: number; series: { time: string; cum_pnl: string }[] }
  /** No strategy trades: value null, n 0, series []. */
  win_rate: { value: string | null; n: number; window: number; series: { time: string; value: string }[] }
  avg_r: { value: string | null; n: number; window: number; series: { time: string; value: string }[] }
  /** Room to the FundedNext max-loss floor of one account; null when no account limits are set. */
  max_loss: HomeMaxLoss | null
}

/** Where the equity of `max_loss` comes from: a live MT5 snapshot, the balance, or closed trades only. */
export type EquitySource = 'mt5' | 'balance' | 'trades'

export interface HomeMaxLoss {
  account_id: number
  account_name: string
  /** Distance to the floor in % of the account size: positive = room left, 0 = limit hit. */
  pct: string | null
  /** The floor, e.g. "-10.0000". */
  limit_pct: string
  equity: string | null
  equity_source: EquitySource
  series: { time: string; pct: string }[]
}

export interface HomePosition {
  trade_id: number
  symbol: string
  direction: string
  volume: string
  account_id: number
  account_name: string
  /** ISO UTC. */
  open_time: string
  entry_price: string
  initial_sl: string | null
  tp: string | null
  /** Live values: null without a snapshot or when it is older than 5 minutes. */
  current_price: string | null
  /** Time of the snapshot (ISO UTC), kept when it is stale; null when there is none. */
  price_time: string | null
  pnl: string | null
  r_now: string | null
  /** Signed; r_now / tp_r are null without a usable SL (missing or not on the losing side). */
  tp_r: string | null
  mae_r: string | null
  mfe_r: string | null
  risk_pct: string | null
  described: boolean
  /** MT5 no longer reports the position; its close is not in the history yet (no live values). */
  close_unconfirmed: boolean
}

export interface HomeData {
  now: string
  timezone: string
  session: HomeSession
  bias_today: HomeBiasToday
  /** null when there is no active account. */
  limits: HomeLimits | null
  kpis: HomeKpis
  open_positions: HomePosition[]
  /** pnl / risk_pct null when any position lacks the value (no partial sums). */
  open_totals: { pnl: string | null; risk_pct: string | null; price_time: string | null }
}

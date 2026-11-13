/** `GET /api/dashboard` and `GET /api/digests/suggestion` (docs/api.md "## M6"). Decimals are strings. */
import type { InboxCounts } from '@/features/inbox/api'

export const LIMIT_STATES = ['ok', 'stop_loss', 'stop_profit'] as const
export type LimitState = (typeof LIMIT_STATES)[number]

/** Money 2 dp, percents 4 dp (of the account size). */
export interface PeriodBlock {
  pnl: string
  pct: string
  low_pnl: string
  low_pct: string
  high_pnl: string
  high_pct: string
}

/** 4 dp percent strings; `null` = the stop rule is disabled in rules.yaml. */
export interface DashboardLimits {
  daily_loss_pct: string | null
  daily_profit_pct: string | null
  weekly_loss_pct: string | null
  weekly_profit_pct: string | null
}

export interface DashboardAccount {
  id: number
  name: string
  currency: string
  account_size: string
  today: PeriodBlock
  week: PeriodBlock
  limits: DashboardLimits
  today_state: LimitState
  week_state: LimitState
}

export interface OpenPosition {
  trade_id: number
  account_name: string
  symbol: string
  direction: string
  volume: string
  entry_price: string
  /** ISO UTC. */
  open_time: string
  initial_sl: string | null
  risk_amount: string | null
  risk_pct: string | null
}

export interface Dashboard {
  now: string
  accounts: DashboardAccount[]
  stop: { today: boolean; week: boolean }
  open_positions: OpenPosition[]
  inbox: InboxCounts
}

export interface PeriodRef {
  period_start: string
}

export interface DigestSuggestion {
  weekly: PeriodRef | null
  monthly: PeriodRef | null
}

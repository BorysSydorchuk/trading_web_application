/** Digests API types (docs/api.md "## M6", backend/tests/test_digests_api.py). Decimals are strings. */

export const DIGEST_KINDS = ['weekly', 'monthly'] as const
export type DigestKind = (typeof DIGEST_KINDS)[number]

export function isDigestKind(value: string | null | undefined): value is DigestKind {
  return value != null && (DIGEST_KINDS as readonly string[]).includes(value)
}

/** One row of `GET /api/digests?kind=`; a virtual row (no digest yet) has `id: null`. */
export interface DigestListItem {
  id: number | null
  kind: DigestKind
  period_start: string
  period_end: string
  generated_at: string | null
  trades: number
  net_pnl: string
  net_pnl_pct: string | null
  total_r: string | null
  win_rate: string | null
  reviewed: boolean
  /** UTC ISO or null. */
  reviewed_at: string | null
}

export type Deviation = 'worse' | 'better' | null

export interface MetricValue {
  /** Counts are numbers; money 2 dp, the rest 4 dp strings; null when undefined. */
  value: string | number | null
  norm_mean: string | null
  norm_sd: string | null
  deviation: Deviation
  /** `total_r` only: trades with an R multiple. */
  n?: number
}

export const METRIC_NAMES = [
  'trades',
  'wins',
  'losses',
  'breakeven',
  'net_pnl',
  'net_pnl_pct',
  'win_rate',
  'total_r',
  'avg_win_r',
  'avg_loss_r',
  'expectancy_r',
  'profit_factor',
  'max_drawdown',
  'max_drawdown_pct',
  'violations',
] as const
export type MetricName = (typeof METRIC_NAMES)[number]

export interface TradeRef {
  trade_id: number
  symbol: string
  net_pnl: string
  r_multiple: string | null
  close_time: string
}

export interface MetricBlock {
  norm_available: boolean
  metrics: Partial<Record<MetricName, MetricValue>>
  best_trade: TradeRef | null
  worst_trade: TradeRef | null
}

export interface AccountMetricBlock extends MetricBlock {
  account_id: number
  account_name: string
}

export type GroupKey = string | number | boolean | null

export interface BreakdownGroup {
  key: GroupKey
  trades: number
  net_pnl: string
  total_r: string
  win_rate: string | null
}

export interface Breakdown {
  groups: BreakdownGroup[]
  coverage: { filled: number; total: number }
}

export interface RuleLine {
  rule_key: string
  violations: number
  trades: number
  pnl: string
}

export interface RulesSection {
  rules: RuleLine[]
  violated_trades: number
  violated_pnl: string
}

export interface BiasSide {
  trades: number
  net_pnl: string
  total_r: string
}

export interface BiasScope {
  accuracy: { value: string | null; marked: number; total: number }
  aligned: BiasSide
  counter: BiasSide
}

export const BIAS_SCOPES = ['daily', 'weekly', 'monthly'] as const
export type BiasScopeName = (typeof BIAS_SCOPES)[number]

export interface EquityPoint {
  time: string
  cum_pnl: string
}

export interface RBucket {
  lower: string
  upper: string
  count: number
}

export interface HeatCell {
  weekday: number
  hour: number
  trades: number
  net_pnl: string
}

export interface DigestCharts {
  equity: { combined: EquityPoint[]; by_account: { account_id: number; points: EquityPoint[] }[] }
  r_distribution: RBucket[]
  hour_heatmap: HeatCell[]
}

export interface DigestSnapshot {
  currency: string | null
  combined: MetricBlock
  by_account: AccountMetricBlock[]
  breakdowns: Record<string, Breakdown>
  rules: RulesSection
  bias: Partial<Record<BiasScopeName, BiasScope>>
  charts: DigestCharts
  trade_ids: number[]
}

export interface Digest {
  id: number
  kind: DigestKind
  period_start: string
  period_end: string
  generated_at: string | null
  what_worked: string | null
  what_to_fix: string | null
  focus_next: string | null
  ai_summary: string | null
  reviewed: boolean
  /** UTC ISO or null. */
  reviewed_at: string | null
  next_bias_note_id: number | null
  metrics: DigestSnapshot
}

export const REVIEW_FIELDS = ['what_worked', 'what_to_fix', 'focus_next'] as const
export type ReviewField = (typeof REVIEW_FIELDS)[number]
export type ReviewInput = Record<ReviewField, string>

/** Server limit per review text (docs/api.md PATCH). */
export const REVIEW_MAX_LENGTH = 10_000

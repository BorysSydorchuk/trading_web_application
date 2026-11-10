/** Calculator API types (docs/api.md M5, "M5-04c/d exact shapes"). Decimals are strings end to end. */

export type Direction = 'buy' | 'sell'

export interface SymbolSpec {
  /** Canonical name (config/symbols.yaml); the value sent to calculate / margin-requests. */
  symbol: string
  /** The broker's own name for it (e.g. GER30 for GER40 at FundedNext); MT5 calls only. */
  broker_symbol: string
  contract_size: string
  /** null = not synced yet (the calculator answers specs_incomplete). */
  point: string | null
  tick_size: string
  tick_value_loss: string | null
  volume_min: string
  volume_step: string
  volume_max: string
  digits: number
  currency_profit: string
  currency_margin: string
  synced_at: string
}

export interface SymbolSpecList {
  /** Already in display order (symbols.yaml order, then others by name). */
  items: SymbolSpec[]
  /** Canonical names configured in symbols.yaml but not found at this broker. */
  missing: string[]
}

/** POST /api/calculator/calculate and /margin-requests body: exactly one SL and at most one risk field. */
export interface CalculateInput {
  account_id: number
  symbol: string
  direction: Direction
  entry: string
  sl_price?: string
  sl_points?: string
  risk_percent?: string
  risk_amount?: string
}

export interface MarginInfo {
  source: 'cached_estimate' | 'unavailable'
  amount: string | null
  currency: string | null
  calculated_at: string | null
  sample_price: string | null
  sample_volume: string | null
  reason: 'no_cached_margin' | null
}

export interface CalculateResult {
  account_id: number
  symbol: string
  direction: Direction
  entry: string
  sl_price: string
  sl_distance: string
  sl_points: string
  balance: string
  balance_source: 'reference' | 'synced'
  balance_synced_at: string | null
  currency: string
  risk_percent: string | null
  risk_amount: string | null
  risk_budget: string
  volume: string
  actual_risk: string
  actual_risk_percent: string
  tp_1_5: string
  tp_2: string
  tp_3: string
  specs_at: string
  margin: MarginInfo
}

export type MarginRequestStatus = 'pending' | 'processing' | 'done' | 'failed' | 'expired'

export interface MarginRequest {
  id: number
  account_id: number
  symbol: string
  direction: Direction
  volume: string
  entry: string
  status: MarginRequestStatus
  source: 'mt5' | null
  amount: string | null
  currency: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  expires_at: string
  error_code: string | null
}

/** Test data for the calculator (docs/api.md M5-04c/d shapes). */
import type { Account } from '@/features/accounts/types'
import type { CalculateResult, MarginRequest, SymbolSpec } from './types'

export function account(overrides: Partial<Account> = {}): Account {
  return {
    id: 1, name: 'FN Phase 1', firm: 'FundedNext', program: 'Stellar', phase: 'phase_1', login: 1234567,
    server: 'FundedNext-Server', terminal_path: null, starting_balance: '100000.00', currency: 'USD', status: 'active',
    reference_balance: '100000.00', daily_loss_pct: null, max_drawdown_pct: null, profit_target_pct: null,
    password_env_key: 'MT5_PASSWORD_1234567', password_configured: true, balance: '101250.40', equity: '101250.40',
    balance_synced_at: '2026-11-10T07:00:00Z', server_offset_hours: 2, created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z', ...overrides,
  }
}

/** broker_symbol defaults to the (overridden) canonical symbol. */
export function spec(overrides: Partial<SymbolSpec> = {}): SymbolSpec {
  return {
    symbol: 'XAUUSD', broker_symbol: overrides.symbol ?? 'XAUUSD', contract_size: '100', point: '0.01', tick_size: '0.01', tick_value_loss: '1',
    volume_min: '0.01', volume_step: '0.01', volume_max: '50', digits: 2, currency_profit: 'USD',
    currency_margin: 'USD', synced_at: '2026-11-10T06:00:00Z', ...overrides,
  }
}

export function result(overrides: Partial<CalculateResult> = {}): CalculateResult {
  return {
    account_id: 1, symbol: 'XAUUSD', direction: 'buy', entry: '2650.50', sl_price: '2645.50',
    sl_distance: '5.00', sl_points: '500', balance: '100000.00', balance_source: 'reference',
    balance_synced_at: null, currency: 'USD', risk_percent: '1.0', risk_amount: null,
    risk_budget: '1000.000', volume: '2.00000000', actual_risk: '1000.00000000',
    actual_risk_percent: '1.000000', tp_1_5: '2658.00', tp_2: '2660.50', tp_3: '2665.50',
    specs_at: '2026-11-10T06:00:00Z',
    margin: {
      source: 'cached_estimate', amount: '5301.00', currency: 'USD', calculated_at: '2026-11-09T09:00:00Z',
      sample_price: '2640.00000000', sample_volume: '1.00000000', reason: null,
    },
    ...overrides,
  }
}

export const NO_MARGIN: CalculateResult['margin'] = {
  source: 'unavailable', amount: null, currency: null, calculated_at: null, sample_price: null,
  sample_volume: null, reason: 'no_cached_margin',
}

export function marginRequest(overrides: Partial<MarginRequest> = {}): MarginRequest {
  return {
    id: 41, account_id: 1, symbol: 'XAUUSD', direction: 'buy', volume: '2.00', entry: '2650.50',
    status: 'pending', source: null, amount: null, currency: 'USD', created_at: '2026-11-10T08:00:00Z',
    started_at: null, finished_at: null, expires_at: '2026-11-10T08:01:00Z', error_code: null, ...overrides,
  }
}

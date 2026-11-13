/** Test data for `GET /api/dashboard` (docs/api.md "Dashboard API", M6-03 details). */
import type { Dashboard, DashboardAccount, OpenPosition, PeriodBlock } from './types'

export function periodBlock(overrides: Partial<PeriodBlock> = {}): PeriodBlock {
  return { pnl: '0.00', pct: '0.0000', low_pnl: '0.00', low_pct: '0.0000', high_pnl: '0.00', high_pct: '0.0000', ...overrides }
}

export function dashboardAccount(overrides: Partial<DashboardAccount> = {}): DashboardAccount {
  return {
    id: 1,
    name: 'FTMO 100k',
    currency: 'USD',
    account_size: '100000.00',
    today: periodBlock(),
    week: periodBlock(),
    limits: { daily_loss_pct: '-3.0000', daily_profit_pct: '5.0000', weekly_loss_pct: '-6.0000', weekly_profit_pct: '10.0000' },
    today_state: 'ok',
    week_state: 'ok',
    ...overrides,
  }
}

export function openPosition(overrides: Partial<OpenPosition> = {}): OpenPosition {
  return {
    trade_id: 10,
    account_name: 'FTMO 100k',
    symbol: 'XAUUSD',
    direction: 'buy',
    volume: '0.50',
    entry_price: '2650.12000000',
    open_time: '2026-11-13T08:05:00Z',
    initial_sl: '2640.00000000',
    risk_amount: '506.00',
    risk_pct: '0.5060',
    ...overrides,
  }
}

export function emptyDashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    now: '2026-11-13T10:00:00Z',
    accounts: [],
    stop: { today: false, week: false },
    open_positions: [],
    inbox: { needs_sl: 0, needs_description: 0, draft: 0 },
    ...overrides,
  }
}

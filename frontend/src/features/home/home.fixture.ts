/** Test data for `GET /api/home` (docs/api.md "## M8-10b"), values like the PM mockup. */
import type { HomeCharts } from '@/features/dashboard/homeCharts/api'
import type { HomeData, HomeLimits, HomeMaxLoss, HomePosition } from './types'

export const HOME_NOW = '2026-11-19T13:42:00Z'

export function homeLimits(overrides: Partial<HomeLimits> = {}): HomeLimits {
  return {
    account_id: 1,
    account_name: 'Funded',
    currency: 'USD',
    day: { pct: '2.1000', loss_pct: '-3.0000', profit_pct: '5.0000' },
    week: { pct: '2.5000', loss_pct: '-6.0000', profit_pct: '10.0000' },
    month: { pct: '3.1000', loss_pct: '-10.0000', profit_pct: '10.0000' },
    trades_week: 7,
    max_trades_week: 10,
    to_daily_stop_pct: '5.1000',
    floating_pnl: null,
    floating_included: false,
    balance: null,
    equity: null,
    balance_fresh: false,
    ...overrides,
  }
}

export function homePosition(overrides: Partial<HomePosition> = {}): HomePosition {
  return {
    trade_id: 41,
    symbol: 'GER40',
    direction: 'buy',
    volume: '0.13',
    account_id: 1,
    account_name: 'Funded',
    open_time: '2026-11-19T12:44:00Z',
    entry_price: '26480.50000000',
    initial_sl: '26430.00000000',
    tp: '26556.25000000',
    current_price: '26523.40000000',
    price_time: '2026-11-19T13:41:30Z',
    pnl: '64.20',
    pnl_pct: '0.6420',
    r_now: '0.7000',
    tp_r: '1.5000',
    mae_r: '0.2000',
    mfe_r: '0.8000',
    risk_pct: '0.6560',
    described: true,
    close_unconfirmed: false,
    ...overrides,
  }
}

const dayTime = (i: number) => `2026-11-${String(i + 1).padStart(2, '0')}T10:00:00Z`
const valueSeries = (values: readonly string[]) => values.map((value, i) => ({ time: dayTime(i), value }))
const pctSeries = (values: readonly string[]) => values.map((pct, i) => ({ time: dayTime(i), pct }))

export function homeMaxLoss(overrides: Partial<HomeMaxLoss> = {}): HomeMaxLoss {
  return {
    account_id: 1,
    account_name: 'Funded',
    pct: '10.5625',
    limit_pct: '-10.0000',
    equity: '10056.25',
    equity_source: 'mt5',
    series: pctSeries(['10.0000', '10.2000', '9.8000', '10.5625']),
    ...overrides,
  }
}

export function homeData(overrides: Partial<HomeData> = {}): HomeData {
  return {
    now: HOME_NOW,
    timezone: 'Europe/Brussels',
    session: { key: 'ny', entries_allowed: true },
    bias_today: { pre_london: [{ symbol: 'EURUSD', direction: 'bullish' }, { symbol: 'GER40', direction: 'bullish' }], pre_ny_missing: true },
    limits: homeLimits(),
    kpis: {
      today: {
        pnl: '212.40',
        pct: '2.1240',
        trades: 3,
        accounts_counted: 1,
        series: [
          { time: '2026-11-18T23:00:00Z', cum_pnl: '0.00', cum_pct: '0.0000' },
          { time: '2026-11-19T08:30:00Z', cum_pnl: '45.00', cum_pct: '0.4500' },
          { time: '2026-11-19T10:10:00Z', cum_pnl: '110.00', cum_pct: '1.1000' },
          { time: '2026-11-19T13:30:00Z', cum_pnl: '212.40', cum_pct: '2.1240' },
        ],
      },
      win_rate: { value: '57.0000', n: 20, window: 20, series: valueSeries(['45.0000', '48.0000', '46.0000', '50.0000', '57.0000']) },
      avg_r: { value: '1.3000', n: 20, window: 20, series: valueSeries(['0.6000', '0.7000', '0.9000', '1.3000']) },
      max_loss: homeMaxLoss(),
    },
    open_positions: [],
    open_totals: { pnl: null, pnl_pct: null, risk_pct: null, price_time: null },
    ...overrides,
  }
}

/** `GET /api/dashboard/charts` for November with a P&L curve, daily bars and the rolling form. */
export function homeCharts(cum: readonly string[] = ['0.00', '120.00', '30.00', '340.00', '741.00']): HomeCharts {
  return {
    from: '2026-11-01',
    to: '2026-11-19',
    currency: 'USD',
    account_size: '10000.00',
    trades: cum.length - 1,
    equity: cum.map((v, i) => ({
      time: i === 0 ? '2026-10-31T23:00:00Z' : dayTime(i),
      cum_pnl: v,
      cum_pct: (Number(v) / 100).toFixed(4),
    })),
    daily: [
      { day: '2026-11-16', net_pnl: '120.00', pct: '1.2000', trades: 1 },
      { day: '2026-11-17', net_pnl: '-90.00', pct: '-0.9000', trades: 2 },
      { day: '2026-11-18', net_pnl: '310.00', pct: '3.1000', trades: 1 },
      { day: '2026-11-19', net_pnl: '401.00', pct: '4.0100', trades: 2 },
    ],
    rolling: [
      { time: '2026-11-16T10:00:00Z', n: 18, win_rate: '45.0000', avg_r: '0.6000' },
      { time: '2026-11-18T10:00:00Z', n: 19, win_rate: '50.0000', avg_r: '0.9000' },
      { time: '2026-11-19T10:00:00Z', n: 20, win_rate: '57.0000', avg_r: '1.3000' },
    ],
    rolling_window: 20,
    total_pct: (Number(cum[cum.length - 1] ?? '0') / 100).toFixed(4),
    total_r: '3.2000',
    accounts_counted: 1,
  }
}

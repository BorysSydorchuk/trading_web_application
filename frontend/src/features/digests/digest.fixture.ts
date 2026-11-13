/** Test fixtures in the docs/api.md M6 digest shapes. Tests only. */
import type { Digest, DigestListItem, MetricBlock, MetricValue } from './types'

function m(value: MetricValue['value'], overrides: Partial<MetricValue> = {}): MetricValue {
  return { value, norm_mean: null, norm_sd: null, deviation: null, ...overrides }
}

export function fixtureBlock(overrides: Partial<MetricBlock> = {}): MetricBlock {
  return {
    norm_available: true,
    metrics: {
      trades: m(4),
      wins: m(1),
      losses: m(3),
      breakeven: m(0),
      net_pnl: m('-120.50', { norm_mean: '80.00', norm_sd: '40.00', deviation: 'worse' }),
      net_pnl_pct: m('-1.2050', { norm_mean: '0.8000', norm_sd: '0.4000', deviation: 'worse' }),
      win_rate: m('25.0000', { norm_mean: '62.5000', norm_sd: '12.5000', deviation: 'worse' }),
      total_r: m('3.5000', { norm_mean: '1.0000', norm_sd: '0.5000', deviation: 'better', n: 3 }),
      avg_win_r: m('5.0000'),
      avg_loss_r: m('-0.7500'),
      expectancy_r: m('1.1667'),
      profit_factor: m(null),
      max_drawdown: m('200.00'),
      max_drawdown_pct: m('2.0000'),
      violations: m(1),
    },
    best_trade: { trade_id: 41, symbol: 'GER40', net_pnl: '250.00', r_multiple: '5.0000', close_time: '2026-11-10T13:30:00Z' },
    worst_trade: { trade_id: 42, symbol: 'XAUUSD', net_pnl: '-150.00', r_multiple: '-1.0000', close_time: '2026-11-11T09:00:00Z' },
    ...overrides,
  }
}

export function fixtureDigest(overrides: Partial<Digest> = {}): Digest {
  return {
    id: 5,
    kind: 'weekly',
    period_start: '2026-11-09',
    period_end: '2026-11-15',
    generated_at: '2026-11-14T12:00:00Z',
    what_worked: null,
    what_to_fix: null,
    focus_next: null,
    ai_summary: null,
    reviewed: false,
    reviewed_at: null,
    next_bias_note_id: null,
    metrics: {
      currency: 'USD',
      combined: fixtureBlock(),
      by_account: [{ account_id: 1, account_name: 'Alpha', ...fixtureBlock({ norm_available: false }) }],
      breakdowns: {
        symbol: {
          groups: [{ key: 'GER40', trades: 4, net_pnl: '-120.50', total_r: '3.5000', win_rate: '25.0000' }],
          coverage: { filled: 4, total: 4 },
        },
        entry_model: {
          groups: [
            { key: 'qm', trades: 3, net_pnl: '100.00', total_r: '4.0000', win_rate: '33.3333' },
            { key: null, trades: 1, net_pnl: '-220.50', total_r: '-0.5000', win_rate: '0.0000' },
          ],
          coverage: { filled: 3, total: 4 },
        },
      },
      rules: {
        rules: [{ rule_key: 'max_risk_pct', violations: 1, trades: 1, pnl: '-150.00' }],
        violated_trades: 1,
        violated_pnl: '-150.00',
      },
      bias: {
        daily: { accuracy: { value: '66.6667', marked: 3, total: 4 }, aligned: { trades: 2, net_pnl: '200.00', total_r: '4.0000' }, counter: { trades: 1, net_pnl: '-150.00', total_r: '-1.0000' } },
        weekly: { accuracy: { value: '100.0000', marked: 1, total: 1 }, aligned: { trades: 3, net_pnl: '100.00', total_r: '3.0000' }, counter: { trades: 0, net_pnl: '0.00', total_r: '0.0000' } },
        monthly: { accuracy: { value: null, marked: 0, total: 1 }, aligned: { trades: 0, net_pnl: '0.00', total_r: '0.0000' }, counter: { trades: 0, net_pnl: '0.00', total_r: '0.0000' } },
      },
      charts: {
        equity: {
          combined: [
            { time: '2026-11-10T13:30:00Z', cum_pnl: '250.00' },
            { time: '2026-11-11T09:00:00Z', cum_pnl: '100.00' },
          ],
          by_account: [{ account_id: 1, points: [{ time: '2026-11-10T13:30:00Z', cum_pnl: '250.00' }] }],
        },
        r_distribution: [
          { lower: '-3.0000', upper: '-2.5000', count: 1 },
          { lower: '-2.5000', upper: '-2.0000', count: 0 },
          { lower: '3.0000', upper: '3.5000', count: 2 },
        ],
        hour_heatmap: [
          { weekday: 0, hour: 9, trades: 2, net_pnl: '100.00' },
          { weekday: 5, hour: 14, trades: 1, net_pnl: '-50.00' },
        ],
      },
      trade_ids: [41, 42, 43, 44],
    },
    ...overrides,
  }
}

export function fixtureListItem(overrides: Partial<DigestListItem> = {}): DigestListItem {
  return {
    id: 5,
    kind: 'weekly',
    period_start: '2026-11-09',
    period_end: '2026-11-15',
    generated_at: '2026-11-14T12:00:00Z',
    trades: 4,
    net_pnl: '-120.50',
    net_pnl_pct: '-1.2050',
    total_r: '3.5000',
    win_rate: '25.0000',
    reviewed: false,
    reviewed_at: null,
    ...overrides,
  }
}

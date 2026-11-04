/** Test fixture: a closed trade in the GET /api/trades/{id} shape (docs/api.md). Tests only. */
import type { TradeDetail } from '@/features/trades/types'
import { FIXTURE_FIELDS } from './journalFields.fixture'

/** Every YAML key (fields and text_keys) present and empty, like an undescribed trade. */
function emptyJournal(): Record<string, null> {
  const keys = FIXTURE_FIELDS.flatMap((field) => (field.text_key ? [field.key, field.text_key] : [field.key]))
  return Object.fromEntries(keys.filter((key) => key !== 'chart_links').map((key) => [key, null]))
}

export function fixtureTrade(overrides: Partial<TradeDetail> = {}): TradeDetail {
  return {
    id: 7,
    account_id: 1,
    account_name: 'FTMO 100k',
    position_id: 123456,
    symbol: 'EURUSD',
    direction: 'buy',
    status: 'needs_description',
    open_time: '2026-11-03T08:15:00Z',
    close_time: '2026-11-03T09:40:00Z',
    duration_seconds: 5100,
    entry_price: '1.08500',
    exit_price: '1.08800',
    volume: '1.00',
    initial_sl: '1.08350',
    last_sl: '1.08350',
    tp: '1.08800',
    commission: '-7.00',
    swap: '0.00',
    gross_pnl: '300.00',
    net_pnl: '293.00',
    pnl_pct: '0.29',
    balance_at_open: '100000.00',
    risk_amount: '150.00',
    risk_pct: '0.15',
    r_multiple: '1.95',
    planned_rr: '2.00',
    session: 'london',
    weekday: 1,
    hour: 9,
    is_reentry: false,
    violations: [],
    initial_sl_source: 'mt5',
    exit_deals: [],
    rule_violations: [],
    journal: emptyJournal(),
    chart_links: [],
    raw_text: null,
    transcript: null,
    audio_notes: [],
    ai_filled_fields: [],
    described_at: null,
    missing_required: [],
    ...overrides,
  }
}

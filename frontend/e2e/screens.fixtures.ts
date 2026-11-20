/**
 * Fictitious API data for e2e/screens.spec.ts (M8-10c): Journal, Describe, Bias, Digests, Calculator
 * and Settings. Shapes follow docs/api.md and the frontend types; no real account data.
 */

const named = (value: string, label: string, deprecated = false) => ({ value, label, deprecated })
const CONTEXTS = [named('flow', 'Flow'), named('reversal', 'Reversal'), named('range', 'Range'), named('other', 'Інше')]
const FVG_TYPES = [named('fractal_updating', 'оновлює фрактал'), named('post_manipulation', 'після маніпуляції'), named('other', 'Інше')]
const EMOTIONS = [
  named('calm', 'спокій'), named('confidence', 'впевненість'), named('fomo', 'FOMO'), named('fear', 'страх'),
  named('revenge', 'реванш'), named('fatigue', 'втома'), named('boredom', 'нудьга'),
]
const VIOLATIONS = {
  max_risk_pct: ['ризик на угоду вище ліміту', 'auto'],
  daily_risk: ['Порушення денного ризику', 'auto'],
  entry_session: ['вхід поза дозволеною сесією', 'auto'],
  entry_not_by_model: ['Вхід не за моделлю входу', 'manual'],
  entry_weak_poi: ['Вхід від слабкої POI', 'manual'],
} as const
const field = (key: string, label: string, type: string, extra: Record<string, unknown> = {}) => ({
  key, label, type, required: true, analytics: true, storage: 'column', show_if: null, legacy: false, ...extra,
})
const other = (key: string) => ({ text_key: `${key}_other`, allow_other_text: true })

/** GET /api/journal-fields: config/journal_fields.yaml in the API shape. */
export const JOURNAL_FIELDS = {
  fields: [
    field('h1_context', 'Контекст H1', 'enum', { options: CONTEXTS, ...other('h1_context') }),
    field('h4_context', 'Контекст H4', 'enum', { options: CONTEXTS, ...other('h4_context') }),
    field('poi_types', 'POI', 'multi_enum', {
      options: [named('fvg_h4', 'FVG H4'), named('fvg_h1', 'FVG H1'), named('fractal_h1', 'Fractal H1'), named('fractal_h4', 'Fractal H4'), named('other', 'Інше')],
      ...other('poi_types'),
    }),
    field('fvg_types_h1', 'Тип FVG H1', 'multi_enum', { options: FVG_TYPES, ...other('fvg_types_h1'), show_if: { field: 'poi_types', includes: 'fvg_h1' } }),
    field('fvg_types_h4', 'Тип FVG H4', 'multi_enum', { options: FVG_TYPES, ...other('fvg_types_h4'), show_if: { field: 'poi_types', includes: 'fvg_h4' } }),
    field('entry_model', 'Модель входу', 'enum', { options: [named('ifvg_m5', 'IFVG M5'), named('qm_m5', 'QM M5'), named('other', 'Інше')], ...other('entry_model') }),
    field('setup_context', 'Контекст (Flow H1 синхронний з H4)', 'enum', {
      options: [named('yes', 'так'), named('no', 'ні'), named('partially', 'частково')], required: false, analytics: false, legacy: true,
    }),
    field('exit_reason', 'Причина виходу', 'enum', {
      options: [
        named('fractal_update', 'оновлення фракталу'), named('point_b', 'ціль: точка B'), named('sl', 'SL'), named('tp', 'TP'),
        named('stop_out', 'стоп-аут'), named('manual', 'вручну'), named('other', 'інше'),
      ],
      phase: 'after',
    }),
    field('bias_alignment', 'Відповідність біасу', 'auto', {
      options: [named('aligned', 'за біасом'), named('counter', 'проти біасу'), named('neutral_bias', 'нейтральний біас'), named('no_bias', 'без біасу')],
      required: false,
    }),
    field('followed_plan', 'Дотримався плану', 'bool', { phase: 'after' }),
    field('rule_violations', 'Порушення правил', 'multi_enum', {
      required: false,
      options: Object.entries(VIOLATIONS).map(([key, [label]]) => named(key, label)),
      violation_types: Object.fromEntries(Object.entries(VIOLATIONS).map(([key, [, type]]) => [key, type])),
    }),
    field('emotion_before', 'Емоція до входу', 'enum', { options: EMOTIONS, text_key: 'emotion_before_text', allow_other_text: false }),
    field('emotion_after', 'Емоція після угоди', 'enum', { options: EMOTIONS, text_key: 'emotion_after_text', allow_other_text: false, phase: 'after' }),
    field('mistakes', 'Помилки', 'text', { required: false, analytics: false, phase: 'after' }),
    field('lesson', 'Урок', 'text', { required: false, analytics: false, phase: 'after' }),
    field('quality_rating', 'Якість сетапу (1–5, незалежно від результату)', 'int', { min: 1, max: 5 }),
    field('chart_links', 'Посилання на графік (TradingView)', 'links', { options: [named('before', 'до входу'), named('after', 'після угоди')], analytics: false }),
  ],
}

const hourIso = (day: number, hour: number, minute = 0) =>
  `2026-11-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00Z`

interface RowSpec {
  id: number
  symbol: string
  direction: 'buy' | 'sell'
  status: string
  day: number
  hour: number
  minutes: number | null
  entry: string
  exit: string | null
  sl: string | null
  pnl: string | null
  r: string | null
  account?: 2
  session?: string
  violations?: string[]
  excluded?: string
  mfe?: string
}

function tradeRow(s: RowSpec) {
  const open = hourIso(s.day, s.hour, 15)
  const closed = s.minutes !== null
  const risk = s.sl ? '100.00' : null
  return {
    id: s.id, account_id: s.account ?? 1, account_name: s.account === 2 ? 'Demo B' : 'Demo A', position_id: 5000 + s.id,
    symbol: s.symbol, direction: s.direction, status: s.status, open_time: open,
    close_time: closed ? hourIso(s.day, s.hour + Math.floor((15 + (s.minutes ?? 0)) / 60), (15 + (s.minutes ?? 0)) % 60) : null,
    duration_seconds: closed ? (s.minutes ?? 0) * 60 : null, entry_price: s.entry, exit_price: s.exit, volume: '0.25',
    initial_sl: s.sl, last_sl: s.sl, tp: null, commission: '-1.75', swap: '0.00', gross_pnl: s.pnl, net_pnl: s.pnl,
    pnl_pct: s.pnl === null ? null : (Number(s.pnl) / 100).toFixed(4), balance_at_open: '30000.00', risk_amount: risk,
    risk_pct: risk ? '1.0000' : null, r_multiple: s.r, planned_rr: s.sl ? '2.00' : null, session: s.session ?? 'london',
    weekday: (s.day + 5) % 7, hour: s.hour + 1, is_reentry: false, bias_alignment: s.id % 3 === 0 ? 'counter' : 'aligned',
    bias_alignment_weekly: 'aligned', bias_alignment_monthly: null, violations: s.violations ?? [],
    excluded_from_stats: s.excluded !== undefined, excluded_reason: s.excluded ?? null, excluded_at: s.excluded ? hourIso(s.day, 18) : null,
    mfe_r: s.r && closed ? (s.mfe ?? (Math.max(Number(s.r), 0) + 0.4).toFixed(4)) : null,
    mae_r: s.r && closed ? '0.3500' : null, excursion_status: closed ? 'final' : 'running',
  }
}

export const JOURNAL_TRADES = {
  items: [
    tradeRow({ id: 28, symbol: 'GER40', direction: 'buy', status: 'open', day: 19, hour: 12, minutes: null, entry: '26480.50', exit: null, sl: '26430.00', pnl: null, r: null, session: 'ny' }),
    tradeRow({ id: 27, symbol: 'XAUUSD', direction: 'sell', status: 'needs_description', day: 19, hour: 8, minutes: 95, entry: '4112.40', exit: '4098.10', sl: '4120.00', pnl: '357.50', r: '1.8800' }),
    tradeRow({ id: 26, symbol: 'EURUSD', direction: 'buy', status: 'complete', day: 18, hour: 13, minutes: 48, entry: '1.10420', exit: '1.10320', sl: '1.10320', pnl: '-100.00', r: '-1.0000', session: 'ny' }),
    tradeRow({ id: 25, symbol: 'GER40', direction: 'sell', status: 'complete', day: 18, hour: 8, minutes: 130, entry: '26610.00', exit: '26520.00', sl: '26650.00', pnl: '225.00', r: '2.2500' }),
    tradeRow({ id: 24, symbol: 'GBPUSD', direction: 'sell', status: 'draft', day: 17, hour: 9, minutes: 62, entry: '1.29880', exit: '1.29720', sl: '1.29980', pnl: '160.00', r: '1.6000' }),
    tradeRow({ id: 23, symbol: 'XAUUSD', direction: 'buy', status: 'needs_sl', day: 17, hour: 14, minutes: 20, entry: '4080.00', exit: '4084.20', sl: null, pnl: '105.00', r: null, session: 'ny', account: 2 }),
    tradeRow({
      id: 22, symbol: 'EURUSD', direction: 'sell', status: 'complete', day: 14, hour: 15, minutes: 35, entry: '1.10010', exit: '1.10160', sl: '1.10110',
      pnl: '-150.00', r: '-1.5000', session: 'ny', violations: ['entry_session', 'max_risk_pct'], account: 2,
    }),
    tradeRow({
      id: 21, symbol: 'GER40', direction: 'buy', status: 'complete', day: 13, hour: 8, minutes: 12, entry: '26205.00', exit: '26215.00', sl: '26170.00',
      pnl: '25.00', r: '0.2900', excluded: 'Тестовий вхід після оновлення терміналу',
    }),
  ],
  total: 8,
}

export const TRADE_SYMBOLS = { items: ['EURUSD', 'GBPUSD', 'GER40', 'XAUUSD'] }

const base24 = JOURNAL_TRADES.items.find((row) => row.id === 24) ?? JOURNAL_TRADES.items[0]

/** GET /api/trades/24: a draft with AI-prefilled taxonomy fields (marked until touched). */
export const DESCRIBE_TRADE = {
  ...base24,
  tp: '1.29680', exit_reason_source: 'mt5_reason', bias_note_ids: { daily: 41, weekly: 44, monthly: null },
  initial_sl_source: 'mt5',
  exit_deals: [{ ticket: 88124, time: base24?.close_time, price: '1.29720', volume: '0.25', profit: '161.75', commission: '-1.75', swap: '0.00', reason: 'client', reason_code: 0 }],
  rule_violations: [],
  journal: {
    h1_context: 'flow', h1_context_other: null, h4_context: 'reversal', h4_context_other: null,
    poi_types: ['fvg_h1', 'fractal_h4'], poi_types_other: null, fvg_types_h1: ['post_manipulation'], fvg_types_h1_other: null,
    fvg_types_h4: null, fvg_types_h4_other: null, entry_model: 'ifvg_m5', entry_model_other: null, setup_context: null,
    exit_reason: 'point_b', bias_alignment: 'aligned', followed_plan: true, rule_violations: [],
    emotion_before: 'calm', emotion_before_text: null, emotion_after: null, emotion_after_text: null,
    mistakes: null, lesson: 'Частковий вихід у точці B, решта по оновленню фракталу.', quality_rating: 4,
  },
  chart_links: [{ id: 301, url: 'https://www.tradingview.com/x/DemoChart1/', kind: 'before', preview_url: null }],
  raw_text: 'Лондон, Flow на H1, на H4 розворот. Вхід IFVG M5 від FVG H1 після маніпуляції, вихід у точці B. Спокійно, за планом.',
  transcript: null, audio_notes: [],
  ai_filled_fields: ['h1_context', 'h4_context', 'poi_types', 'fvg_types_h1', 'entry_model', 'exit_reason', 'emotion_before'],
  described_at: '2026-11-17T12:05:00Z', missing_required: ['emotion_after'], missing_new_fields: [], exclusion_history: [],
  mfe_price: '1.29610', mfe_points: '270', mfe_time: '2026-11-17T09:58:00Z', mae_price: '1.29915', mae_points: '35',
  mae_time: '2026-11-17T09:21:00Z', excursion_source: 'mt5_ticks', excursion_at: '2026-11-17T10:20:00Z',
}

const entry = (id: number, symbol: string, direction: string, levels: string | null, narrative: string | null, confidence: number, wasCorrect: boolean | null) => ({
  id, symbol, direction, key_levels: levels, narrative, confidence, chart_links: [], was_correct: wasCorrect,
  was_correct_source: wasCorrect === null ? null : 'owner', ai_filled_fields: [],
})
const note = (id: number, kind: string, date: string, entries: unknown[], rawText: string | null = null) => ({
  id, kind, period_date: date, raw_text: rawText, entries, audio_notes: [], created_at: `${date}T06:50:00Z`, updated_at: `${date}T06:55:00Z`,
})

export const BIAS_NOTE = note(41, 'pre_london', '2026-11-19', [
  entry(401, 'EURUSD', 'bullish', '1.1020 FVG H4, 1.1080 high', 'H4 розворот від FVG, чекаю маніпуляцію під азію.', 3, null),
  entry(402, 'GER40', 'bullish', '26400 Fractal H1', 'Flow H1, купівлі від POI на відкритті.', 2, null),
  entry(403, 'XAUUSD', 'neutral', '4080 / 4130 range', null, 1, null),
], 'Євро вгору від FVG H4, DAX продовжує flow, золото в рейнджі.')

export const MONTHLY_BIAS_NOTE = note(38, 'monthly', '2026-11-01', [entry(371, 'EURUSD', 'bullish', '1.0850 monthly FVG', 'Місяць від монтлі FVG угору.', 2, null)])

export const BIAS_NOTES = {
  items: [
    BIAS_NOTE,
    note(44, 'weekly', '2026-11-16', [
      entry(411, 'EURUSD', 'bullish', '1.0980 weekly low', 'Тижневий контекст бичачий, ціль 1.1120.', 2, null),
      entry(412, 'GER40', 'bullish', '26000', null, 2, null),
    ]),
    note(40, 'pre_ny', '2026-11-18', [
      entry(391, 'EURUSD', 'bearish', '1.1045 FVG M15', 'Відкат перед NY.', 1, false),
      entry(392, 'XAUUSD', 'bullish', '4085', null, 2, true),
    ]),
    note(39, 'pre_london', '2026-11-18', [
      entry(381, 'GER40', 'bearish', '26650 high', 'Зняття ліквідності над high, продажі.', 3, true),
      entry(382, 'GBPUSD', 'no_trade', null, 'Новини о 10:00, не торгую.', 1, null),
    ]),
    MONTHLY_BIAS_NOTE,
  ],
}

export const BIAS_CONFIG = {
  symbols: ['EURUSD', 'GBPUSD', 'XAUUSD', 'GER40'].map((symbol) => ({ symbol, aliases: [] })),
  reminders: { pre_london: { from: '07:45', until: '11:00' }, pre_ny: { from: '12:30', until: '16:00' } },
  kinds: ['pre_london', 'pre_ny', 'weekly', 'monthly'],
}

const mv = (value: string | number | null, normMean: string | null = null, deviation: 'worse' | 'better' | null = null, n?: number) => ({
  value, norm_mean: normMean, norm_sd: normMean === null ? null : '0.5000', deviation, ...(n === undefined ? {} : { n }),
})
function block(o: { trades: number; wins: number; pnl: string; pct: string; wr: string; r: string; dd: string; violations: number }) {
  return {
    norm_available: true,
    metrics: {
      trades: mv(o.trades), wins: mv(o.wins), losses: mv(o.trades - o.wins - 1), breakeven: mv(1),
      net_pnl: mv(o.pnl, '820.00', Number(o.pnl) > 820 ? 'better' : 'worse'), net_pnl_pct: mv(o.pct, '2.7300', Number(o.pct) > 2.73 ? 'better' : 'worse'),
      win_rate: mv(o.wr, '50.0000', 'better'), total_r: mv(o.r, '5.0000', null, o.trades - 1), avg_win_r: mv('1.9200'), avg_loss_r: mv('-0.9600'),
      expectancy_r: mv('0.5100'), profit_factor: mv('1.8700'), max_drawdown: mv(o.dd), max_drawdown_pct: mv((Number(o.dd) / 300).toFixed(4), '1.5000', 'worse'),
      violations: mv(o.violations, '2.0000', o.violations > 2 ? 'worse' : null),
    },
    best_trade: { trade_id: 25, symbol: 'GER40', net_pnl: '225.00', r_multiple: '2.2500', close_time: '2026-11-18T10:25:00Z' },
    worst_trade: { trade_id: 22, symbol: 'EURUSD', net_pnl: '-150.00', r_multiple: '-1.5000', close_time: '2026-11-14T15:50:00Z' },
  }
}
const g = (key: unknown, trades: number, pnl: string, r: string, wr: string | null) => ({ key, trades, net_pnl: pnl, total_r: r, win_rate: wr })
const cum = ['0', '120', '60', '310', '240', '420', '385', '610', '560', '790', '990', '890', '1100', '1241.20']

/** GET /api/digests/by-period?kind=monthly&date=2026-10-01: a reviewed monthly snapshot. */
export const MONTHLY_DIGEST = {
  id: 6, kind: 'monthly', period_start: '2026-10-01', period_end: '2026-10-31', generated_at: '2026-11-01T09:00:00Z',
  what_worked: 'Входи IFVG M5 у Лондоні за біасом, вихід у точці B.',
  what_to_fix: 'Два входи в NY поза дозволеною сесією; один перезахід після SL.',
  focus_next: 'Тільки Лондон для EURUSD, перезахід лише після нового фракталу.',
  ai_summary: 'Жовтень у плюсі: +1241.20 USD (4.14%). Найкраще працює IFVG M5 від FVG H1 у Лондоні (WR 64%). Порушення сесії коштували -310 USD.',
  ai_summary_stale_at: null, reviewed: true, reviewed_at: '2026-11-02T08:30:00Z', next_bias_note_id: 38,
  metrics: {
    currency: 'USD',
    combined: block({ trades: 22, wins: 12, pnl: '1241.20', pct: '4.1373', wr: '54.5455', r: '11.3000', dd: '410.00', violations: 3 }),
    by_account: [
      { account_id: 1, account_name: 'Demo A', ...block({ trades: 15, wins: 9, pnl: '1080.40', pct: '3.6013', wr: '60.0000', r: '9.1000', dd: '260.00', violations: 1 }) },
      { account_id: 2, account_name: 'Demo B', ...block({ trades: 7, wins: 3, pnl: '160.80', pct: '1.6080', wr: '42.8571', r: '2.2000', dd: '310.00', violations: 2 }), norm_available: false },
    ],
    breakdowns: {
      symbol: { kind: 'field', groups: [g('GER40', 9, '820.00', '6.4000', '66.6667'), g('EURUSD', 7, '210.20', '2.9000', '42.8571'), g('XAUUSD', 6, '211.00', '2.0000', '50.0000')], coverage: { filled: 22, total: 22 } },
      session: { kind: 'field', groups: [g('london', 15, '1551.20', '12.6000', '60.0000'), g('ny', 7, '-310.00', '-1.3000', '42.8571')], coverage: { filled: 22, total: 22 } },
      entry_model: { kind: 'field', groups: [g('ifvg_m5', 14, '1180.00', '9.8000', '64.2857'), g('qm_m5', 6, '91.20', '1.9000', '50.0000'), g(null, 2, '-30.00', '-0.4000', '0.0000')], coverage: { filled: 20, total: 22 } },
      poi_types: { kind: 'field', groups: [g('fvg_h1', 10, '760.00', '6.2000', '60.0000'), g('fvg_h4', 8, '540.00', '4.4000', '62.5000'), g('fractal_h4', 5, '-58.80', '-0.3000', '40.0000')], coverage: { filled: 21, total: 22 } },
      poi_types__combo: { kind: 'combination', groups: [g('fvg_h1', 8, '640.00', '5.1000', '62.5000'), g('fvg_h4 + fractal_h4', 4, '220.00', '1.9000', '50.0000'), g('fvg_h4', 4, '320.00', '2.5000', '75.0000')], coverage: { filled: 21, total: 22 } },
      h1_context__x__h4_context: {
        kind: 'matrix',
        groups: [g(['flow', 'flow'], 9, '910.00', '7.6000', '66.6667'), g(['flow', 'reversal'], 5, '330.00', '2.8000', '60.0000'), g(['range', 'reversal'], 4, '-120.00', '-1.2000', '25.0000'), g(['reversal', null], 2, '121.20', '1.1000', '50.0000')],
        coverage: { filled: 20, total: 22 },
      },
    },
    rules: {
      rules: [{ rule_key: 'entry_session', violations: 2, trades: 2, pnl: '-250.00' }, { rule_key: 'max_risk_pct', violations: 1, trades: 1, pnl: '-60.00' }],
      violated_trades: 3, violated_pnl: '-310.00',
    },
    bias: {
      daily: { accuracy: { value: '68.7500', marked: 16, total: 20 }, aligned: { trades: 15, net_pnl: '1420.00', total_r: '12.4000' }, counter: { trades: 5, net_pnl: '-210.00', total_r: '-2.0000' } },
      weekly: { accuracy: { value: '75.0000', marked: 4, total: 4 }, aligned: { trades: 18, net_pnl: '1300.00', total_r: '11.8000' }, counter: { trades: 4, net_pnl: '-58.80', total_r: '-0.5000' } },
      monthly: { accuracy: { value: '100.0000', marked: 1, total: 1 }, aligned: { trades: 22, net_pnl: '1241.20', total_r: '11.3000' }, counter: { trades: 0, net_pnl: '0.00', total_r: '0.0000' } },
    },
    charts: {
      equity: {
        combined: cum.map((v, i) => ({ time: i === 0 ? '2026-09-30T22:00:00Z' : `2026-10-${String(1 + i * 2).padStart(2, '0')}T14:00:00Z`, cum_pnl: v })),
        by_account: [
          { account_id: 1, points: cum.map((v, i) => ({ time: i === 0 ? '2026-09-30T22:00:00Z' : `2026-10-${String(1 + i * 2).padStart(2, '0')}T14:00:00Z`, cum_pnl: (Number(v) * 0.87).toFixed(2) })) },
          { account_id: 2, points: cum.map((v, i) => ({ time: i === 0 ? '2026-09-30T22:00:00Z' : `2026-10-${String(1 + i * 2).padStart(2, '0')}T14:00:00Z`, cum_pnl: (Number(v) * 0.13).toFixed(2) })) },
        ],
      },
      r_distribution: [
        ['-2.0', '-1.5', 1], ['-1.5', '-1.0', 3], ['-1.0', '-0.5', 5], ['-0.5', '0.0', 1], ['0.0', '0.5', 1],
        ['0.5', '1.0', 2], ['1.0', '1.5', 3], ['1.5', '2.0', 3], ['2.0', '2.5', 2], ['2.5', '3.0', 1],
      ].map(([lower, upper, count]) => ({ lower: `${lower}000`, upper: `${upper}000`, count })),
      hour_heatmap: [
        [0, 9, 3, '310.00'], [0, 10, 1, '-100.00'], [1, 9, 2, '180.00'], [1, 15, 1, '-150.00'], [2, 8, 2, '240.00'], [2, 10, 1, '95.00'],
        [3, 9, 3, '420.00'], [3, 14, 2, '-100.00'], [4, 9, 2, '210.00'], [4, 15, 1, '-60.00'], [1, 10, 2, '196.20'],
      ].map(([weekday, hour, trades, pnl]) => ({ weekday, hour, trades, net_pnl: pnl })),
    },
    trade_ids: [21, 22, 23, 24, 25, 26, 27],
    excluded: {
      trades: 2, net_pnl: '-85.00', account_net_pnl: '1156.20', account_net_pnl_pct: '3.8540',
      items: [
        { trade_id: 15, account_id: 1, account_name: 'Demo A', symbol: 'GER40', close_time: '2026-10-08T09:30:00Z', net_pnl: '-110.00', reason: 'Тестовий вхід після оновлення терміналу' },
        { trade_id: 17, account_id: 2, account_name: 'Demo B', symbol: 'XAUUSD', close_time: '2026-10-21T14:10:00Z', net_pnl: '25.00', reason: 'Помилковий вхід (не той рахунок)' },
      ],
    },
    excursions: { n_winners: 12, n_losers: 9, winners_avg_mfe_r: '2.4100', losers_avg_mfe_r: '0.6200', losers_reached_1r: 3, losers_reached_1r_share: '33.3333' },
  },
}

export const DIGEST_LIST_MONTHLY = {
  items: [
    { id: null, kind: 'monthly', period_start: '2026-11-01', period_end: '2026-11-30', generated_at: null, trades: 18, net_pnl: '1241.20', net_pnl_pct: '4.1373', total_r: '9.8000', win_rate: '55.5556', reviewed: false, reviewed_at: null },
    { id: 6, kind: 'monthly', period_start: '2026-10-01', period_end: '2026-10-31', generated_at: '2026-11-01T09:00:00Z', trades: 22, net_pnl: '1241.20', net_pnl_pct: '4.1373', total_r: '11.3000', win_rate: '54.5455', reviewed: true, reviewed_at: '2026-11-02T08:30:00Z' },
    { id: 3, kind: 'monthly', period_start: '2026-09-01', period_end: '2026-09-30', generated_at: '2026-10-01T09:00:00Z', trades: 19, net_pnl: '-340.00', net_pnl_pct: '-1.1333', total_r: '-2.7000', win_rate: '36.8421', reviewed: true, reviewed_at: '2026-10-02T08:00:00Z' },
  ],
}

const account = (o: Record<string, unknown>) => ({
  firm: 'Demo Prop', program: 'Two-Step', phase: 'phase_1', server: 'DemoBroker-Server', terminal_path: 'C:\\MT5\\demo-a\\terminal64.exe',
  currency: 'USD', status: 'active', daily_loss_pct: '5.00', max_drawdown_pct: '10.00', profit_target_pct: '8.00', password_configured: true,
  server_offset_hours: 2, starting_balance_suggestion: null, created_at: '2026-10-01T08:00:00Z', updated_at: '2026-11-19T07:00:00Z', ...o,
})

export const ACCOUNTS = {
  items: [
    account({
      id: 1, name: 'Demo A', login: 1000001, password_env_key: 'MT5_PASSWORD_1000001', starting_balance: '30000.00', reference_balance: '30000.00',
      balance: '31241.20', equity: '31305.40', balance_synced_at: '2026-11-19T13:41:00Z',
    }),
    account({
      id: 2, name: 'Demo B', phase: 'funded', program: 'Instant', login: 1000002, password_env_key: 'MT5_PASSWORD_1000002', terminal_path: 'C:\\MT5\\demo-b\\terminal64.exe',
      starting_balance: '10000.00', reference_balance: '10000.00', balance: '10160.80', equity: '10132.80', balance_synced_at: '2026-11-19T13:40:00Z',
      daily_loss_pct: '3.00', max_drawdown_pct: '6.00', profit_target_pct: null, starting_balance_suggestion: { amount: '10050.00', time: '2026-10-02T07:12:00Z' },
    }),
  ],
}

const spec = (symbol: string, o: Record<string, unknown>) => ({
  symbol, broker_symbol: symbol, contract_size: '100000', point: '0.00001', tick_size: '0.00001', tick_value_loss: '1',
  volume_min: '0.01', volume_step: '0.01', volume_max: '50', digits: 5, currency_profit: 'USD', currency_margin: 'USD',
  synced_at: '2026-11-19T06:00:00Z', ...o,
})

export const SYMBOL_SPECS = {
  items: [
    spec('EURUSD', { currency_margin: 'EUR' }),
    spec('GBPUSD', { currency_margin: 'GBP' }),
    spec('XAUUSD', { contract_size: '100', point: '0.01', tick_size: '0.01', digits: 2 }),
    spec('GER40', { broker_symbol: 'GER40.cash', contract_size: '1', point: '0.01', tick_size: '0.01', tick_value_loss: '0.011', digits: 2, currency_profit: 'EUR', currency_margin: 'EUR' }),
  ],
  missing: [],
}

/** Calculator inputs typed by the spec and the POST /api/calculator/calculate answer for them. */
export const CALC_INPUT = { symbol: 'XAUUSD', entry: '4100.50', sl: '4092.50', risk: '1' }
export const CALC_RESULT = {
  account_id: 1, symbol: 'XAUUSD', direction: 'buy', entry: '4100.50', sl_price: '4092.50', sl_distance: '8.00', sl_points: '800',
  balance: '30000.00', balance_source: 'account_size', balance_synced_at: null, current_balance: '31241.20',
  current_balance_synced_at: '2026-11-19T13:41:00Z', currency: 'USD', risk_percent: '1', risk_amount: null, risk_budget: '300.000',
  volume: '0.37000000', actual_risk: '296.00000000', actual_risk_percent: '0.986667', tp_1_5: '4112.50', tp_2: '4116.50', tp_3: '4124.50',
  specs_at: '2026-11-19T06:00:00Z', loss_per_tick: '1.00000000', conversion: null,
  margin: {
    source: 'cached_estimate', amount: '1517.19', currency: 'USD', calculated_at: '2026-11-19T07:00:00Z',
    sample_price: '4095.00000000', sample_volume: '1.00000000', reason: null,
  },
}
export const MARGIN_REQUEST = {
  id: 91, account_id: 1, symbol: 'XAUUSD', direction: 'buy', volume: '0.37', entry: '4100.50', status: 'done', source: 'mt5',
  amount: '1517.19', currency: 'USD', created_at: '2026-11-19T13:42:00Z', started_at: '2026-11-19T13:42:01Z',
  finished_at: '2026-11-19T13:42:02Z', expires_at: '2026-11-19T13:43:00Z', error_code: null,
}

export const AI_MODELS = {
  models: [
    { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', approx_usd: { trade_extraction: '0.02', bias_extraction: '0.02', digest_summary: '0.06' } },
    { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', approx_usd: { trade_extraction: '0.08', bias_extraction: '0.07', digest_summary: '0.25' } },
  ],
  defaults: { trade_extraction: 'claude-sonnet-5-5', bias_extraction: 'claude-sonnet-5-5', digest_summary: 'claude-opus-5-5' },
}

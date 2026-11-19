/**
 * Test fixture: a subset of config/journal_fields.yaml in the GET /api/journal-fields shape
 * (one field of every type, incl. an `other` text_key and a plain note text_key). Tests only.
 */
import type { JournalField } from '@/features/trades/types'

const opt = (value: string, deprecated = false) => ({ value, label: value, deprecated })

export const FIXTURE_FIELDS: readonly JournalField[] = [
  {
    key: 'setup_context',
    label: 'Контекст',
    type: 'enum',
    options: [opt('yes'), opt('no'), opt('partially')],
    required: true,
    storage: 'column',
  },
  {
    key: 'poi_type',
    label: 'Тип POI',
    type: 'enum',
    options: [opt('fvg_h4'), opt('fvg_h1'), opt('other')],
    required: true,
    storage: 'column',
    text_key: 'poi_type_other',
    allow_other_text: true,
  },
  {
    key: 'bias_alignment',
    label: 'Відповідність біасу',
    type: 'auto',
    options: [opt('aligned'), opt('counter')],
    required: false,
    storage: 'column',
  },
  { key: 'followed_plan', label: 'Дотримався плану', type: 'bool', required: true, storage: 'column', phase: 'after' },
  {
    key: 'rule_violations',
    label: 'Порушення правил',
    type: 'multi_enum',
    options: [opt('max_risk_pct'), opt('entry_session')],
    required: false,
    storage: 'column',
  },
  {
    key: 'emotion_before',
    label: 'Емоція до входу',
    type: 'enum',
    options: [opt('calm'), opt('fomo')],
    required: true,
    storage: 'column',
    text_key: 'emotion_before_text',
    allow_other_text: false,
  },
  { key: 'mistakes', label: 'Помилки', type: 'text', required: false, storage: 'column', phase: 'after' },
  { key: 'quality_rating', label: 'Якість', type: 'int', min: 1, max: 5, required: true, storage: 'column' },
  {
    key: 'chart_links',
    label: 'Посилання',
    type: 'links',
    options: [opt('before'), opt('after')],
    required: true,
    storage: 'column',
  },
]

const named = (value: string, label: string, deprecated = false) => ({ value, label, deprecated })
const CONTEXTS = [named('flow', 'Flow'), named('reversal', 'Reversal'), named('range', 'Range'), named('other', 'Інше')]
const FVG_TYPES = [named('fractal_updating', 'оновлює фрактал'), named('post_manipulation', 'після маніпуляції'), named('other', 'Інше')]

/**
 * M8-04..08 taxonomy subset in the merge B GET /api/journal-fields shape: show_if children,
 * multi_enum with «Інше» text, legacy fields, violations from violations.yaml. Tests only.
 */
export const TAXONOMY_FIELDS: readonly JournalField[] = [
  { key: 'h1_context', label: 'Контекст H1', type: 'enum', options: CONTEXTS, required: true, analytics: true, storage: 'column', text_key: 'h1_context_other', allow_other_text: true, show_if: null, legacy: false },
  { key: 'h4_context', label: 'Контекст H4', type: 'enum', options: CONTEXTS, required: true, analytics: true, storage: 'column', text_key: 'h4_context_other', allow_other_text: true, show_if: null, legacy: false },
  {
    key: 'poi_types',
    label: 'POI',
    type: 'multi_enum',
    options: [named('fvg_h4', 'FVG H4'), named('fvg_h1', 'FVG H1'), named('fractal_h1', 'Fractal H1'), named('fractal_h4', 'Fractal H4'), named('other', 'Інше')],
    required: true,
    analytics: true,
    storage: 'column',
    text_key: 'poi_types_other',
    allow_other_text: true,
    show_if: null,
    legacy: false,
  },
  { key: 'fvg_types_h1', label: 'Тип FVG H1', type: 'multi_enum', options: FVG_TYPES, required: true, analytics: true, storage: 'column', text_key: 'fvg_types_h1_other', allow_other_text: true, show_if: { field: 'poi_types', includes: 'fvg_h1' }, legacy: false },
  { key: 'fvg_types_h4', label: 'Тип FVG H4', type: 'multi_enum', options: FVG_TYPES, required: true, analytics: true, storage: 'column', text_key: 'fvg_types_h4_other', allow_other_text: true, show_if: { field: 'poi_types', includes: 'fvg_h4' }, legacy: false },
  {
    key: 'entry_model',
    label: 'Модель входу',
    type: 'enum',
    options: [named('ifvg_m5', 'IFVG M5'), named('qm_m5', 'QM M5'), named('other', 'Інше')],
    required: true,
    analytics: true,
    storage: 'column',
    text_key: 'entry_model_other',
    allow_other_text: true,
    show_if: null,
    legacy: false,
  },
  {
    key: 'setup_context',
    label: 'Контекст (Flow H1 синхронний з H4)',
    type: 'enum',
    options: [named('yes', 'так'), named('no', 'ні'), named('partially', 'частково')],
    required: false,
    analytics: false,
    storage: 'column',
    show_if: null,
    legacy: true,
  },
  {
    key: 'fvg_kind',
    label: 'Тип FVG (старе)',
    type: 'enum',
    options: [named('fractal_updating', 'оновлює фрактал'), named('post_manipulation', 'після маніпуляції'), named('na', 'н/з')],
    required: false,
    analytics: false,
    storage: 'column',
    show_if: null,
    legacy: true,
  },
  {
    key: 'rule_violations',
    label: 'Порушення правил',
    type: 'multi_enum',
    options: [
      named('daily_risk', 'Порушення денного ризику'),
      named('entry_weak_poi', 'Вхід від слабкої POI'),
      named('daily_stop_loss_pct', 'вхід після денного стоп-лосу', true),
    ],
    violation_types: { daily_risk: 'auto', entry_weak_poi: 'manual', daily_stop_loss_pct: 'auto' },
    required: false,
    analytics: true,
    storage: 'column',
    show_if: null,
    legacy: false,
  },
]

/** Every TAXONOMY_FIELDS key (fields and text_keys) empty, plus the old poi_type columns. */
export function emptyTaxonomyJournal(): Record<string, null> {
  const keys = TAXONOMY_FIELDS.flatMap((field) => (field.text_key ? [field.key, field.text_key] : [field.key]))
  return Object.fromEntries([...keys, 'poi_type', 'poi_type_other'].map((key) => [key, null]))
}

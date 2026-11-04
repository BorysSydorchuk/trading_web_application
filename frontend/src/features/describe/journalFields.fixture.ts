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
  { key: 'followed_plan', label: 'Дотримався плану', type: 'bool', required: true, storage: 'column' },
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
  { key: 'mistakes', label: 'Помилки', type: 'text', required: false, storage: 'column' },
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

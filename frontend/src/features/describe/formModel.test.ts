import { describe, expect, it } from 'vitest'
import type { JournalField } from '@/features/trades/types'
import { newLinkRow } from './chartLinks'
import {
  aiFilledForSave,
  buildFields,
  fieldsForTrade,
  initialValues,
  missingKeys,
  renderedKeys,
  type FormValues,
} from './formModel'
import { FIXTURE_FIELDS } from './journalFields.fixture'

const BEFORE = newLinkRow('https://www.tradingview.com/x/AbCd1234/', 'before')
const AFTER = newLinkRow('https://www.tradingview.com/x/Other1/', 'after')

const COMPLETE: FormValues = {
  setup_context: 'yes',
  poi_type: 'fvg_h4',
  poi_type_other: null,
  followed_plan: true,
  rule_violations: [],
  emotion_before: 'calm',
  emotion_before_text: null,
  mistakes: null,
  quality_rating: '4',
}

describe('buildFields', () => {
  it('sends every key except auto and links', () => {
    const payload = buildFields(FIXTURE_FIELDS, COMPLETE)
    expect(Object.keys(payload).sort()).toEqual(
      [
        'emotion_before',
        'emotion_before_text',
        'followed_plan',
        'mistakes',
        'poi_type',
        'poi_type_other',
        'quality_rating',
        'rule_violations',
        'setup_context',
      ].sort(),
    )
    expect(payload).not.toHaveProperty('bias_alignment')
    expect(payload).not.toHaveProperty('chart_links')
  })

  it('converts values to the API types', () => {
    expect(buildFields(FIXTURE_FIELDS, { ...COMPLETE, quality_rating: ' 5 ', mistakes: '  late  ' })).toMatchObject({
      setup_context: 'yes',
      followed_plan: true,
      quality_rating: 5,
      mistakes: 'late',
    })
  })

  it('sends a field of an unknown type back unchanged', () => {
    const fields: JournalField[] = [...FIXTURE_FIELDS, { key: 'session_score', label: 'x', type: 'rating', required: false }]
    const payload = buildFields(fields, { ...COMPLETE, session_score: ['a', 'b'] })
    expect(payload.session_score).toEqual(['a', 'b'])
    expect(buildFields(fields, COMPLETE).session_score).toBeNull()
  })

  it('turns empty values into null', () => {
    const payload = buildFields(FIXTURE_FIELDS, {
      setup_context: '',
      poi_type: null,
      followed_plan: null,
      rule_violations: [],
      emotion_before: '',
      emotion_before_text: '   ',
      mistakes: '  ',
      quality_rating: '',
    })
    expect(Object.values(payload).every((value) => value === null)).toBe(true)
  })

  it('sends multi_enum [] as null and a filled list as a copy', () => {
    const list = ['max_risk_pct']
    expect(buildFields(FIXTURE_FIELDS, { ...COMPLETE, rule_violations: [] }).rule_violations).toBeNull()
    const payload = buildFields(FIXTURE_FIELDS, { ...COMPLETE, rule_violations: list })
    expect(payload.rule_violations).toEqual(list)
    expect(payload.rule_violations).not.toBe(list)
  })

  it('rejects a non-integer int text as null', () => {
    expect(buildFields(FIXTURE_FIELDS, { ...COMPLETE, quality_rating: '4.5' }).quality_rating).toBeNull()
  })

  it('clears an allow_other_text text unless the enum is other', () => {
    const typed = { ...COMPLETE, poi_type_other: ' my zone ' }
    expect(buildFields(FIXTURE_FIELDS, { ...typed, poi_type: 'fvg_h1' }).poi_type_other).toBeNull()
    expect(buildFields(FIXTURE_FIELDS, { ...typed, poi_type: 'other' }).poi_type_other).toBe('my zone')
  })

  it('keeps a plain note text_key for any value', () => {
    const payload = buildFields(FIXTURE_FIELDS, { ...COMPLETE, emotion_before_text: ' tired ' })
    expect(payload.emotion_before_text).toBe('tired')
  })
})

describe('missingKeys', () => {
  it('is empty for a complete form with a before link', () => {
    expect(missingKeys(FIXTURE_FIELDS, COMPLETE, [BEFORE])).toEqual([])
  })

  it('lists required keys in YAML order, chart_links without a before link', () => {
    const values = { ...COMPLETE, setup_context: null, followed_plan: null, quality_rating: ' ' }
    expect(missingKeys(FIXTURE_FIELDS, values, [AFTER])).toEqual([
      'setup_context',
      'followed_plan',
      'quality_rating',
      'chart_links',
    ])
  })

  it('treats false as filled for bool', () => {
    expect(missingKeys(FIXTURE_FIELDS, { ...COMPLETE, followed_plan: false }, [BEFORE])).toEqual([])
  })

  it('requires the other text right after its enum when the enum is other', () => {
    const values = { ...COMPLETE, setup_context: null, poi_type: 'other', poi_type_other: '  ' }
    expect(missingKeys(FIXTURE_FIELDS, values, [BEFORE])).toEqual(['setup_context', 'poi_type_other'])
    expect(missingKeys(FIXTURE_FIELDS, { ...values, poi_type_other: 'zone' }, [BEFORE])).toEqual(['setup_context'])
  })

  it('never requires a plain note text_key', () => {
    expect(missingKeys(FIXTURE_FIELDS, { ...COMPLETE, emotion_before_text: null }, [BEFORE])).toEqual([])
  })
})

describe('renderedKeys', () => {
  it('has fields and note text_keys but not links or a hidden other text', () => {
    const keys = renderedKeys(FIXTURE_FIELDS, COMPLETE)
    expect(keys.has('bias_alignment')).toBe(true)
    expect(keys.has('emotion_before_text')).toBe(true)
    expect(keys.has('poi_type_other')).toBe(false)
    expect(keys.has('chart_links')).toBe(false)
  })

  it('shows the other text when the enum is other', () => {
    expect(renderedKeys(FIXTURE_FIELDS, { ...COMPLETE, poi_type: 'other' }).has('poi_type_other')).toBe(true)
  })
})

describe('initialValues and aiFilledForSave', () => {
  it('maps the journal to form values (int as text, empty multi_enum as [])', () => {
    const values = initialValues(FIXTURE_FIELDS, { quality_rating: 3, rule_violations: null, poi_type: 'other' })
    expect(values.quality_rating).toBe('3')
    expect(values.rule_violations).toEqual([])
    expect(values.poi_type).toBe('other')
    expect(values.poi_type_other).toBeNull()
    expect(values).not.toHaveProperty('chart_links')
  })

  it('keeps only AI keys that are still sent with a value', () => {
    const payload = buildFields(FIXTURE_FIELDS, { ...COMPLETE, poi_type_other: 'x' })
    expect(aiFilledForSave(new Set(['setup_context', 'poi_type_other', 'unknown']), payload)).toEqual(['setup_context'])
  })
})

describe('fieldsForTrade', () => {
  it('returns the same list when the trade has no new required fields', () => {
    expect(fieldsForTrade(FIXTURE_FIELDS, [])).toBe(FIXTURE_FIELDS)
  })

  it('makes fields required after the trade closed optional, without touching the input', () => {
    const scoped = fieldsForTrade(FIXTURE_FIELDS, ['quality_rating', 'chart_links'])
    const required = (key: string) => scoped.find((field) => field.key === key)?.required
    expect(required('quality_rating')).toBe(false)
    expect(required('chart_links')).toBe(false)
    expect(required('setup_context')).toBe(true)
    expect(FIXTURE_FIELDS.find((field) => field.key === 'quality_rating')?.required).toBe(true)
  })

  it('leaves new fields out of the keys that block complete', () => {
    const values: FormValues = { ...COMPLETE, quality_rating: null }
    const scoped = fieldsForTrade(FIXTURE_FIELDS, ['quality_rating', 'chart_links'])
    expect(missingKeys(FIXTURE_FIELDS, values, [])).toEqual(['quality_rating', 'chart_links'])
    expect(missingKeys(scoped, values, [])).toEqual([])
  })
})

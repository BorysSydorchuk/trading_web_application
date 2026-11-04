import { describe, expect, it } from 'vitest'
import type { JournalValue } from '@/features/trades/types'
import { mergeExtraction } from './aiMerge'
import { initialValues, type FormValues } from './formModel'
import { FIXTURE_FIELDS } from './journalFields.fixture'
import type { ExtractResult } from './types'

const EMPTY = initialValues(FIXTURE_FIELDS, {})

function extraction(fields: Record<string, JournalValue>): ExtractResult {
  return {
    fields,
    ai_filled_fields: Object.keys(fields),
    missing_required: [],
    dropped: [],
    usage: { model: 'm', fallback_used: false, input_tokens: 0, output_tokens: 0, cost_usd: null, duration_ms: 0 },
  }
}

function merge(values: FormValues, aiFilled: Iterable<string>, fields: Record<string, JournalValue>) {
  return mergeExtraction(FIXTURE_FIELDS, values, new Set(aiFilled), extraction(fields))
}

describe('mergeExtraction', () => {
  it('fills empty keys and marks them as AI-filled', () => {
    const result = merge(EMPTY, [], { setup_context: 'yes', followed_plan: false, quality_rating: 4 })
    expect(result.values).toMatchObject({ setup_context: 'yes', followed_plan: false, quality_rating: '4' })
    expect([...result.aiFilled].sort()).toEqual(['followed_plan', 'quality_rating', 'setup_context'])
    expect(result.applied).toEqual(['setup_context', 'followed_plan', 'quality_rating'])
  })

  it('never overwrites a value the user typed', () => {
    const values = { ...EMPTY, setup_context: 'no' }
    const result = merge(values, [], { setup_context: 'yes' })
    expect(result.values.setup_context).toBe('no')
    expect(result.aiFilled.has('setup_context')).toBe(false)
    expect(result.applied).toEqual([])
  })

  it('overwrites a key that is still AI-marked', () => {
    const values = { ...EMPTY, setup_context: 'no' }
    expect(merge(values, ['setup_context'], { setup_context: 'yes' }).values.setup_context).toBe('yes')
  })

  it('keeps an earlier AI value and marker when the new result does not mention it', () => {
    const values = { ...EMPTY, setup_context: 'no' }
    const result = merge(values, ['setup_context'], { followed_plan: true })
    expect(result.values.setup_context).toBe('no')
    expect(result.aiFilled.has('setup_context')).toBe(true)
  })

  it('a key the user edited (marker removed) is no longer filled', () => {
    // useDescribeForm drops the marker on edit; aiMerge then treats the key as the user's.
    const first = merge(EMPTY, [], { setup_context: 'yes' })
    const edited = new Set([...first.aiFilled].filter((key) => key !== 'setup_context'))
    const result = mergeExtraction(FIXTURE_FIELDS, { ...first.values, setup_context: 'no' }, edited, extraction({ setup_context: 'partially' }))
    expect(result.values.setup_context).toBe('no')
    expect(result.aiFilled.has('setup_context')).toBe(false)
  })

  it('does not mutate the input values or markers', () => {
    const values = { ...EMPTY }
    const aiFilled = new Set<string>()
    mergeExtraction(FIXTURE_FIELDS, values, aiFilled, extraction({ setup_context: 'yes' }))
    expect(values.setup_context).toBeNull()
    expect(aiFilled.size).toBe(0)
  })

  it('fills the other text after its parent in the same extraction', () => {
    const result = merge(EMPTY, [], { poi_type_other: 'my zone', poi_type: 'other' })
    expect(result.values).toMatchObject({ poi_type: 'other', poi_type_other: 'my zone' })
    expect(result.applied).toEqual(['poi_type', 'poi_type_other'])
  })

  it('skips the other text unless the merged parent is other', () => {
    expect(merge(EMPTY, [], { poi_type: 'fvg_h4', poi_type_other: 'zone' }).values.poi_type_other).toBeNull()
    // The user's own non-other value wins, so the text stays empty too.
    const userValue = { ...EMPTY, poi_type: 'fvg_h1' }
    expect(merge(userValue, [], { poi_type: 'other', poi_type_other: 'zone' }).values.poi_type_other).toBeNull()
  })

  it('fills a plain note text_key for any parent value', () => {
    expect(merge(EMPTY, [], { emotion_before_text: 'tired' }).values.emotion_before_text).toBe('tired')
  })

  it('never fills auto, links or rule_violations', () => {
    const result = merge(EMPTY, [], {
      bias_alignment: 'aligned',
      chart_links: 'https://www.tradingview.com/x/A1/',
      rule_violations: ['max_risk_pct'],
    })
    expect(result.values).toEqual(EMPTY)
    expect(result.applied).toEqual([])
  })

  it('ignores values of the wrong type and empty values', () => {
    const result = merge(EMPTY, [], { quality_rating: 4.5, followed_plan: 'yes', setup_context: '', mistakes: 3 })
    expect(result.values).toEqual(EMPTY)
    expect(result.applied).toEqual([])
  })
})

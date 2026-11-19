import { describe, expect, it } from 'vitest'
import { mergeExtraction } from './aiMerge'
import { buildFields, initialValues, isShown, missingKeys, renderedKeys, toBeCleared } from './formModel'
import { TAXONOMY_FIELDS, emptyTaxonomyJournal } from './journalFields.fixture'
import type { ExtractResult } from './types'

const EMPTY = initialValues(TAXONOMY_FIELDS, emptyTaxonomyJournal())

function field(key: string) {
  const found = TAXONOMY_FIELDS.find((f) => f.key === key)
  if (!found) throw new Error(`no field ${key}`)
  return found
}

function extraction(fields: ExtractResult['fields']): ExtractResult {
  return {
    fields,
    ai_filled_fields: Object.keys(fields),
    missing_required: [],
    dropped: [],
    usage: { model: 'm', fallback_used: false, input_tokens: 1, output_tokens: 1, cost_usd: null, duration_ms: 1 },
  }
}

describe('formModel taxonomy (M8-04..08)', () => {
  it('isShown: show_if matches an enum value or a multi_enum member', () => {
    expect(isShown(field('fvg_types_h1'), { ...EMPTY, poi_types: ['fvg_h4', 'fvg_h1'] })).toBe(true)
    expect(isShown(field('fvg_types_h1'), { ...EMPTY, poi_types: ['fvg_h4'] })).toBe(false)
    expect(isShown({ ...field('fvg_types_h1'), show_if: { field: 'h1_context', includes: 'flow' } }, { ...EMPTY, h1_context: 'flow' })).toBe(true)
    expect(isShown(field('poi_types'), EMPTY)).toBe(true)
  })

  it('missingKeys: hidden and legacy fields never block; a multi «Інше» needs its text', () => {
    const missing = missingKeys(TAXONOMY_FIELDS, { ...EMPTY, poi_types: ['other'] }, [])
    expect(missing).toEqual(['h1_context', 'h4_context', 'poi_types_other', 'entry_model'])
    expect(missingKeys(TAXONOMY_FIELDS, { ...EMPTY, poi_types: ['fvg_h4'] }, [])).toContain('fvg_types_h4')
  })

  it('buildFields: leaves out hidden fields, legacy keys and poi_type; sends the multi «Інше» text', () => {
    const values = { ...EMPTY, poi_types: ['fvg_h4', 'other'], poi_types_other: ' зона ', fvg_types_h1: ['fractal_updating'], setup_context: 'no' }
    const payload = buildFields(TAXONOMY_FIELDS, values)
    expect(payload).toMatchObject({ poi_types: ['fvg_h4', 'other'], poi_types_other: 'зона', fvg_types_h4: null })
    for (const key of ['fvg_types_h1', 'fvg_types_h1_other', 'setup_context', 'fvg_kind', 'poi_type']) {
      expect(payload).not.toHaveProperty(key)
    }
    expect(buildFields(TAXONOMY_FIELDS, { ...values, poi_types: ['fvg_h4'] }).poi_types_other).toBeNull()
  })

  it('toBeCleared lists hidden fields that still hold a value; renderedKeys skips them', () => {
    const values = { ...EMPTY, poi_types: ['fractal_h1'], fvg_types_h1: ['post_manipulation'], fvg_types_h4: [] }
    expect(toBeCleared(TAXONOMY_FIELDS, values).map((f) => f.key)).toEqual(['fvg_types_h1'])
    const rendered = renderedKeys(TAXONOMY_FIELDS, values)
    expect(rendered.has('fvg_types_h1')).toBe(false)
    expect(rendered.has('setup_context')).toBe(false)
  })

  it('AI merge fills a multi «Інше» text and skips hidden show_if fields', () => {
    const merged = mergeExtraction(TAXONOMY_FIELDS, EMPTY, new Set(), extraction({
      poi_types: ['fvg_h4', 'other'],
      poi_types_other: 'зона',
      fvg_types_h4: ['fractal_updating'],
      fvg_types_h1: ['post_manipulation'],
      setup_context: 'yes',
    }))
    expect(merged.values).toMatchObject({ poi_types: ['fvg_h4', 'other'], poi_types_other: 'зона', fvg_types_h4: ['fractal_updating'] })
    expect(merged.values.fvg_types_h1).toEqual([])
    expect(merged.values.setup_context).toBeNull()
  })
})

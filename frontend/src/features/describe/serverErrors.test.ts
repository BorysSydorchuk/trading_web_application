import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/client'
import { uk } from '@/i18n/uk'
import { renderedKeys } from './formModel'
import { FIXTURE_FIELDS } from './journalFields.fixture'
import { NO_SAVE_ERRORS, mapSaveError } from './serverErrors'

const RENDERED = renderedKeys(FIXTURE_FIELDS, { poi_type: 'fvg_h4' })

function validation(paths: Record<string, string>): ApiError {
  return new ApiError('validation_error', 'invalid', 422, { fields: paths })
}

describe('mapSaveError', () => {
  it('puts fields.<key> next to a rendered field', () => {
    const result = mapSaveError(validation({ 'fields.setup_context': 'bad' }), RENDERED)
    expect(result).toEqual({ ...NO_SAVE_ERRORS, fields: { setup_context: uk.describe.form.serverRejected } })
  })

  it('maps chart_links.<i>.url and .kind to the link row index', () => {
    const result = mapSaveError(validation({ 'chart_links.0.url': 'x', 'chart_links.3.kind': 'y' }), RENDERED)
    expect(result.links).toEqual({ 0: uk.describe.links.serverRejected, 3: uk.describe.links.kindRejected })
    expect(result.general).toBe(false)
  })

  it('maps raw_text to the description input', () => {
    expect(mapSaveError(validation({ raw_text: 'too long' }), RENDERED).rawText).toBe(uk.describe.input.rawTextRejected)
  })

  it.each([
    ['unknown key', 'fields.not_in_yaml'],
    ['hidden other text', 'fields.poi_type_other'],
    ['links field itself', 'fields.chart_links'],
    ['too many links', 'chart_links'],
    ['unexpected link path', 'chart_links.0.preview_url'],
    ['other body path', 'ai_filled_fields'],
  ])('sends %s to the general message', (_label, path) => {
    const result = mapSaveError(validation({ [path]: 'x' }), RENDERED)
    expect(result.general).toBe(true)
    expect(result.fields).toEqual({})
  })

  it('maps the other text to its field once it is visible', () => {
    const rendered = renderedKeys(FIXTURE_FIELDS, { poi_type: 'other' })
    expect(mapSaveError(validation({ 'fields.poi_type_other': 'x' }), rendered).fields).toEqual({
      poi_type_other: uk.describe.form.serverRejected,
    })
  })

  it('is general when validation details have no fields', () => {
    const error = new ApiError('validation_error', 'invalid', 422, null)
    expect(mapSaveError(error, RENDERED)).toEqual({ ...NO_SAVE_ERRORS, general: true })
  })

  it('returns missing keys for journal_incomplete, dropping non-strings', () => {
    const error = new ApiError('journal_incomplete', 'x', 422, { missing: ['fvg_kind', 3, 'chart_links'] })
    expect(mapSaveError(error, RENDERED)).toEqual({ ...NO_SAVE_ERRORS, missing: ['fvg_kind', 'chart_links'] })
  })

  it('ignores other errors (the toast handles them)', () => {
    expect(mapSaveError(new ApiError('network_error', 'x', 0), RENDERED)).toBe(NO_SAVE_ERRORS)
    expect(mapSaveError(new Error('boom'), RENDERED)).toBe(NO_SAVE_ERRORS)
  })
})

import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/client'
import { uk } from '@/i18n/uk'
import { errorText } from './errors'

function aiError(details: Record<string, unknown> | null): ApiError {
  return new ApiError('ai_error', 'AI failed', 502, details)
}

describe('errorText', () => {
  it.each(Object.entries(uk.errors.ai_error_kinds))('maps ai_error kind %s to its text', (kind, text) => {
    expect(errorText(aiError({ kind }))).toBe(text)
  })

  it.each([
    ['unknown kind', { kind: 'brand_new' }],
    ['non-string kind', { kind: 3 }],
    ['inherited key', { kind: 'toString' }],
    ['no kind', {}],
    ['no details', null],
  ])('falls back to the generic ai_error text for %s', (_label, details) => {
    expect(errorText(aiError(details))).toBe(uk.errors.ai_error)
  })

  it('maps known codes and falls back to unknown', () => {
    expect(errorText(new ApiError('validation_error', 'x', 422))).toBe(uk.errors.validation_error)
    expect(errorText(new ApiError('ai_error_kinds', 'x', 500))).toBe(uk.errors.unknown)
    expect(errorText(new ApiError('something_new', 'x', 500))).toBe(uk.errors.unknown)
    expect(errorText(new Error('boom'))).toBe(uk.errors.unknown)
  })

  describe('config_error', () => {
    function configError(details: Record<string, unknown> | null): ApiError {
      return new ApiError('config_error', 'config broken', 500, details)
    }

    it('names the file for a mojibake config', () => {
      const text = errorText(configError({ file: 'journal_fields.yaml', problems: ['x'], reason: 'mojibake' }))
      expect(text).toBe(uk.errors.config_error_reasons.mojibake('journal_fields.yaml'))
      expect(text).toContain('config/journal_fields.yaml')
    })

    it.each([
      ['no file', { reason: 'mojibake' }],
      ['non-string file', { reason: 'mojibake', file: 42 }],
      ['path in file', { reason: 'mojibake', file: '../secrets/journal_fields.yaml' }],
      ['not a yaml file', { reason: 'mojibake', file: 'notes.txt' }],
      ['markup in file', { reason: 'mojibake', file: '<b>x</b>.yaml' }],
      ['other reason', { reason: 'invalid', file: 'journal_fields.yaml' }],
      ['no reason', { file: 'journal_fields.yaml' }],
      ['no details', null],
    ])('falls back to the generic config_error text for %s', (_label, details) => {
      expect(errorText(configError(details))).toBe(uk.errors.config_error)
    })

    it('does not treat the reasons key as an error code', () => {
      expect(errorText(new ApiError('config_error_reasons', 'x', 500))).toBe(uk.errors.unknown)
    })
  })
})

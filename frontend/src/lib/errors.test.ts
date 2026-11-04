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
})

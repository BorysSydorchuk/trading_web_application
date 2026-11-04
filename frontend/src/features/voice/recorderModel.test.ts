import { describe, expect, it } from 'vitest'
import { baseMimeType, durationSeconds, formatElapsed, micErrorKind, pickMimeType } from './recorderModel'

describe('pickMimeType', () => {
  it('prefers webm/opus when supported', () => {
    expect(pickMimeType(() => true)).toBe('audio/webm;codecs=opus')
  })

  it('falls back to the first supported type (Safari: mp4)', () => {
    expect(pickMimeType((type) => type === 'audio/mp4')).toBe('audio/mp4')
  })

  it('returns undefined when nothing matches, the check throws or is missing', () => {
    expect(pickMimeType(() => false)).toBeUndefined()
    expect(
      pickMimeType(() => {
        throw new Error('boom')
      }),
    ).toBeUndefined()
    expect(pickMimeType(undefined)).toBeUndefined()
  })
})

describe('baseMimeType', () => {
  it.each([
    ['audio/webm;codecs=opus', 'audio/webm'],
    ['Audio/MP4; codecs="mp4a.40.2"', 'audio/mp4'],
    ['audio/ogg', 'audio/ogg'],
    ['', 'audio/webm'],
    [undefined, 'audio/webm'],
  ])('%s → %s', (input, expected) => {
    expect(baseMimeType(input)).toBe(expected)
  })
})

describe('micErrorKind', () => {
  it.each([
    ['NotAllowedError', 'denied'],
    ['SecurityError', 'denied'],
    ['NotFoundError', 'no_mic'],
    ['OverconstrainedError', 'no_mic'],
    ['NotReadableError', 'other'],
  ])('%s → %s', (name, kind) => {
    expect(micErrorKind(new DOMException('x', name))).toBe(kind)
  })

  it('treats non-errors as other', () => {
    expect(micErrorKind('nope')).toBe('other')
    expect(micErrorKind(null)).toBe('other')
  })
})

describe('formatElapsed / durationSeconds', () => {
  it('formats minutes and zero-padded seconds', () => {
    expect(formatElapsed(0)).toBe('0:00')
    expect(formatElapsed(9_999)).toBe('0:09')
    expect(formatElapsed(75_400)).toBe('1:15')
    expect(formatElapsed(600_000)).toBe('10:00')
    expect(formatElapsed(-5)).toBe('0:00')
  })

  it('rounds the duration to 0.1 s', () => {
    expect(durationSeconds(1_549)).toBe(1.5)
    expect(durationSeconds(118_400)).toBe(118.4)
    expect(durationSeconds(-1)).toBe(0)
  })
})

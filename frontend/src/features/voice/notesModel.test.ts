import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import {
  appendTranscript,
  isActive,
  notesToInsert,
  orderedNoteIds,
  progressPercent,
  transcriptionErrorText,
} from './notesModel'
import { fixtureNote } from './note.fixture'

describe('isActive', () => {
  it('is true only while queued or running', () => {
    expect(isActive(fixtureNote({ status: 'pending' }))).toBe(true)
    expect(isActive(fixtureNote({ status: 'processing' }))).toBe(true)
    expect(isActive(fixtureNote({ status: 'done' }))).toBe(false)
    expect(isActive(fixtureNote({ status: 'failed' }))).toBe(false)
    expect(isActive(undefined)).toBe(false)
  })
})

describe('progressPercent', () => {
  it('floors and clamps to 0–100', () => {
    expect(progressPercent(fixtureNote({ progress: 0.459 }))).toBe(45)
    expect(progressPercent(fixtureNote({ progress: null }))).toBe(0)
    expect(progressPercent(fixtureNote({ progress: 1.2 }))).toBe(100)
    expect(progressPercent(fixtureNote({ progress: -0.1 }))).toBe(0)
    expect(progressPercent(fixtureNote({ progress: Number.NaN }))).toBe(0)
  })
})

describe('transcriptionErrorText', () => {
  it.each(Object.entries(uk.errors.transcription))('maps %s', (code, text) => {
    expect(transcriptionErrorText(code)).toBe(text)
  })

  it('falls back to transcription_failed for unknown, inherited and missing codes', () => {
    const fallback = uk.errors.transcription.transcription_failed
    expect(transcriptionErrorText('brand_new')).toBe(fallback)
    expect(transcriptionErrorText('toString')).toBe(fallback)
    expect(transcriptionErrorText(null)).toBe(fallback)
  })
})

describe('appendTranscript', () => {
  it('puts a blank line between the text and the transcript', () => {
    expect(appendTranscript('Вхід від FVG', 'Вихід по TP')).toBe('Вхід від FVG\n\nВихід по TP')
  })

  it('trims trailing whitespace of the text and around the transcript', () => {
    expect(appendTranscript('Вхід\n\n\n  ', '  Вихід  ')).toBe('Вхід\n\nВихід')
  })

  it('uses the transcript alone for an empty text', () => {
    expect(appendTranscript('   ', 'Вихід')).toBe('Вихід')
  })

  it('leaves the text unchanged for an empty transcript', () => {
    expect(appendTranscript('Вхід ', '  ')).toBe('Вхід ')
    expect(appendTranscript('Вхід', null)).toBe('Вхід')
  })
})

describe('orderedNoteIds', () => {
  it('lists trade notes first, then new uploads without duplicates', () => {
    const tradeNotes = [fixtureNote({ id: 1 }), fixtureNote({ id: 2 })]
    expect(orderedNoteIds(tradeNotes, [3, 2, 4])).toEqual([1, 2, 3, 4])
    expect(orderedNoteIds([], [])).toEqual([])
  })
})

describe('notesToInsert', () => {
  it('returns done notes that were not done at open and not inserted yet', () => {
    const notes = [
      fixtureNote({ id: 1, status: 'done' }),
      fixtureNote({ id: 2, status: 'done' }),
      fixtureNote({ id: 3, status: 'done' }),
      fixtureNote({ id: 4, status: 'processing' }),
      undefined,
    ]
    const result = notesToInsert(notes, new Set([1]), new Set([2]))
    expect(result.map((note) => note.id)).toEqual([3])
  })
})

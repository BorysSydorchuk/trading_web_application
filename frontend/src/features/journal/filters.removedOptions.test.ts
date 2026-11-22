import { describe, expect, it } from 'vitest'
import { JOURNAL_NULL_VALUE, withoutRemovedOptions } from './filters'

const FIELDS = [
  { key: 'emotion_before', options: [{ value: 'calm' }, { value: 'fear' }] },
  { key: 'entry_model', options: [{ value: 'ifvg_m5' }] },
]

describe('withoutRemovedOptions', () => {
  it('drops a deleted emotion and keeps the rest and «не заповнено»', () => {
    const journal = { emotion_before: ['calm', 'opt_deleted', JOURNAL_NULL_VALUE] }
    expect(withoutRemovedOptions(journal, FIELDS)).toEqual({ emotion_before: ['calm', JOURNAL_NULL_VALUE] })
  })

  it('removes the key when nothing is left', () => {
    expect(withoutRemovedOptions({ emotion_before: ['opt_deleted'] }, FIELDS)).toEqual({})
  })

  it('leaves fields without an editor and an unloaded field list alone', () => {
    const journal = { entry_model: ['old_value'], emotion_before: ['opt_deleted'] }
    expect(withoutRemovedOptions(journal, undefined)).toBe(journal)
    expect(withoutRemovedOptions({ entry_model: ['old_value'] }, FIELDS)).toEqual({ entry_model: ['old_value'] })
  })
})

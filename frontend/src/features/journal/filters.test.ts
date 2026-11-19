import { describe, expect, it } from 'vitest'
import { clearedFilters, filtersToParams, hasActiveFilters, parseFilters, toTradeQuery, withJournalFilter } from './filters'

const TODAY = '2026-11-04'

function parse(query: string) {
  return parseFilters(new URLSearchParams(query))
}

describe('missing_new_fields filter', () => {
  it('is off by default and stays out of the URL and the API query', () => {
    const filters = parse('')
    expect(filters.missingNewFields).toBe(false)
    expect(filtersToParams(filters).toString()).toBe('')
    expect(toTradeQuery(filters, TODAY)).not.toHaveProperty('missing_new_fields')
    expect(hasActiveFilters(filters)).toBe(false)
  })

  it('reads missing_new_fields=true from the URL and sends it to the API', () => {
    const filters = parse('missing_new_fields=true&status=complete&page=3')
    expect(filters.missingNewFields).toBe(true)
    expect(hasActiveFilters(filters)).toBe(true)
    const query = toTradeQuery(filters, TODAY)
    expect(query.missing_new_fields).toBe(true)
    expect(query.status).toEqual(['complete'])
    expect(query.offset).toBe(100)
  })

  it('ignores values other than "true"', () => {
    expect(parse('missing_new_fields=1').missingNewFields).toBe(false)
    expect(parse('missing_new_fields=false').missingNewFields).toBe(false)
  })

  it('round-trips through the URL together with the other filters', () => {
    const filters = { ...parse('account=2&period=week'), missingNewFields: true }
    const params = filtersToParams(filters)
    expect(params.get('missing_new_fields')).toBe('true')
    expect(parseFilters(params)).toEqual(filters)
  })

  it('round-trips missing_r and counts it as an active filter', () => {
    const f = parse('missing_r=true&period=custom&from=2026-11-09&to=2026-11-15&account=2')
    expect(f.missingR).toBe(true)
    expect(hasActiveFilters(f)).toBe(true)
    expect(filtersToParams(f).get('missing_r')).toBe('true')
    expect(toTradeQuery(f, '2026-11-14')).toMatchObject({ missing_r: true, from: '2026-11-09', to: '2026-11-15', account_id: [2] })
    expect(clearedFilters(f).missingR).toBe(false)
  })

  it('is cleared by "reset filters"', () => {
    expect(clearedFilters(parse('missing_new_fields=true&page=2'))).toMatchObject({
      missingNewFields: false,
      page: 1,
    })
  })
})

describe('M8-01 «Показати виключені» filter', () => {
  it('is on by default: no URL param, no API param, not an active filter', () => {
    const filters = parse('')
    expect(filters.showExcluded).toBe(true)
    expect(filtersToParams(filters).toString()).toBe('')
    expect(toTradeQuery(filters, TODAY)).not.toHaveProperty('excluded')
    expect(hasActiveFilters(filters)).toBe(false)
  })

  it('off hides excluded trades (excluded=false) and round-trips via excluded=hide', () => {
    const filters = { ...parse(''), showExcluded: false }
    const params = filtersToParams(filters)
    expect(params.get('excluded')).toBe('hide')
    expect(parseFilters(params)).toEqual(filters)
    expect(toTradeQuery(filters, TODAY).excluded).toBe(false)
    expect(hasActiveFilters(filters)).toBe(true)
    expect(clearedFilters(filters).showExcluded).toBe(true)
  })
})

describe('M8-15 «Опис» filter', () => {
  it('is «усі» by default: no URL param, no API param', () => {
    const filters = parse('')
    expect(filters.described).toBe('all')
    expect(toTradeQuery(filters, TODAY)).not.toHaveProperty('described')
    expect(hasActiveFilters(filters)).toBe(false)
  })

  it('open trades «з описом» / «без опису» round-trip and reach the API', () => {
    const withText = parse('status=open&described=yes')
    expect(toTradeQuery(withText, TODAY)).toMatchObject({ status: ['open'], described: true })
    expect(parseFilters(filtersToParams(withText))).toEqual(withText)
    const without = parse('status=open&described=no')
    expect(toTradeQuery(without, TODAY).described).toBe(false)
    expect(hasActiveFilters(without)).toBe(true)
    expect(clearedFilters(without).described).toBe('all')
    expect(parse('described=maybe').described).toBe('all')
  })
})

describe('M8-04..08 journal field filters', () => {
  it('parses repeatable journal=<key>:<value>, grouping by key and dropping malformed pairs', () => {
    const f = parse('journal=poi_types:fvg_h1&journal=h1_context:null&journal=poi_types:other&journal=bad&journal=:x&journal=poi_types:fvg_h1&journal=Key:v')
    expect(f.journal).toEqual({ poi_types: ['fvg_h1', 'other'], h1_context: ['null'] })
    expect(hasActiveFilters(f)).toBe(true)
  })

  it('sends the pairs to the API and round-trips them through the URL with the other filters', () => {
    const f = parse('status=complete&journal=fvg_types_h4:post_manipulation&journal=entry_model:null')
    expect(toTradeQuery(f, TODAY)).toMatchObject({
      status: ['complete'],
      journal: ['fvg_types_h4:post_manipulation', 'entry_model:null'],
    })
    const params = filtersToParams(f)
    expect(params.getAll('journal')).toEqual(['fvg_types_h4:post_manipulation', 'entry_model:null'])
    expect(parseFilters(params)).toEqual(f)
  })

  it('drops keys that are not offered filters (bookmarked legacy key → no 422)', () => {
    const f = parse('journal=setup_context:no&journal=poi_type:fvg_h1&journal=h4_context:flow')
    expect(f.journal).toEqual({ h4_context: ['flow'] })
    expect(toTradeQuery(f, TODAY).journal).toEqual(['h4_context:flow'])
  })

  it('is absent from the query by default and cleared by «Скинути фільтри»', () => {
    expect(toTradeQuery(parse(''), TODAY)).not.toHaveProperty('journal')
    expect(clearedFilters(parse('journal=h4_context:flow')).journal).toEqual({})
  })

  it('withJournalFilter replaces one key and removes it when empty, without mutating', () => {
    const start = { poi_types: ['fvg_h1'], h1_context: ['flow'] }
    expect(withJournalFilter(start, 'poi_types', ['other'])).toEqual({ h1_context: ['flow'], poi_types: ['other'] })
    expect(withJournalFilter(start, 'h1_context', [])).toEqual({ poi_types: ['fvg_h1'] })
    expect(start).toEqual({ poi_types: ['fvg_h1'], h1_context: ['flow'] })
  })
})

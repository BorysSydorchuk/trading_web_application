import { describe, expect, it } from 'vitest'
import { clearedFilters, filtersToParams, hasActiveFilters, parseFilters, toTradeQuery } from './filters'

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

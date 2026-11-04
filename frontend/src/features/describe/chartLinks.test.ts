import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import {
  MAX_CHART_LINKS,
  MAX_URL_LENGTH,
  chartUrlKey,
  hasBeforeLink,
  isValidChartUrl,
  linkErrors,
  newLinkRow,
  snapshotPreviewUrl,
} from './chartLinks'

describe('isValidChartUrl', () => {
  it.each([
    'https://www.tradingview.com/x/AbCd1234/',
    'https://www.tradingview.com/x/AbCd1234',
    'https://tradingview.com/x/AbCd1234/',
    'https://uk.tradingview.com/x/AbCd1234/',
    'HTTPS://WWW.TradingView.COM/x/AbCd1234/',
    'https://www.tradingview.com/x/AbCd1234/?utm=1',
    'https://www.tradingview.com/x/AbCd1234/#top',
    'https://www.tradingview.com/x/AbCd1234/?a=1&b=2#frag',
    'https://www.tradingview.com/x/AbCd1234?a=1',
    'https://www.tradingview.com/chart',
    'https://www.tradingview.com/chart/',
    'https://www.tradingview.com/chart/Xy12ab/',
    'https://www.tradingview.com/chart/Xy12ab',
    'https://www.tradingview.com/chart/?symbol=OANDA:XAUUSD',
  ])('accepts %s', (url) => {
    expect(isValidChartUrl(url)).toBe(true)
  })

  it.each([
    ['not https', 'http://www.tradingview.com/x/AbCd1234/'],
    ['host suffix attack', 'https://www.tradingview.com.evil.com/x/AbCd1234/'],
    ['other host', 'https://evil.com/x/AbCd1234/'],
    ['no snapshot id', 'https://www.tradingview.com/x/'],
    ['bad id chars', 'https://www.tradingview.com/x/Ab-Cd/'],
    ['double trailing slash', 'https://www.tradingview.com/x/AbCd1234//'],
    ['upper-case /X/ path', 'https://www.tradingview.com/X/AbCd1234/'],
    ['upper-case /CHART path', 'https://www.tradingview.com/CHART/'],
    ['/charts', 'https://www.tradingview.com/charts/'],
    ['extra chart segment', 'https://www.tradingview.com/chart/Xy12ab/extra/'],
    ['no path', 'https://www.tradingview.com'],
    ['root path', 'https://www.tradingview.com/'],
    ['query without path', 'https://www.tradingview.com?x=1'],
    ['port', 'https://www.tradingview.com:443/x/AbCd1234/'],
    ['userinfo', 'https://user@www.tradingview.com/x/AbCd1234/'],
    ['trailing space', 'https://www.tradingview.com/x/AbCd1234/ '],
    ['trailing newline', 'https://www.tradingview.com/x/AbCd1234/\n'],
    ['leading space', ' https://www.tradingview.com/x/AbCd1234/'],
    ['space in query', 'https://www.tradingview.com/x/AbCd1234/?a b'],
    ['no scheme', 'tradingview.com/x/AbCd1234/'],
    ['empty', ''],
  ])('rejects %s', (_label, url) => {
    expect(isValidChartUrl(url)).toBe(false)
  })

  it('enforces the URL length limit', () => {
    const base = 'https://www.tradingview.com/x/AbCd1234/?q='
    expect(isValidChartUrl(base + 'a'.repeat(MAX_URL_LENGTH - base.length))).toBe(true)
    expect(isValidChartUrl(base + 'a'.repeat(MAX_URL_LENGTH - base.length + 1))).toBe(false)
  })
})

describe('chartUrlKey', () => {
  it.each([
    ['https://www.tradingview.com/x/AbCd1234/', 'https://www.tradingview.com/x/AbCd1234'],
    ['https://www.tradingview.com/x/AbCd1234/', 'HTTPS://WWW.TRADINGVIEW.COM/x/AbCd1234/'],
    ['https://www.tradingview.com/x/AbCd1234/?a=1', 'https://www.tradingview.com/x/AbCd1234#f'],
    ['https://www.tradingview.com/chart', 'https://www.tradingview.com/chart/?symbol=X'],
  ])('treats %s and %s as the same link', (a, b) => {
    expect(chartUrlKey(a)).toBe(chartUrlKey(b))
  })

  it.each([
    ['https://www.tradingview.com/x/AbCd1234/', 'https://www.tradingview.com/x/abcd1234/'],
    ['https://www.tradingview.com/x/AbCd1234/', 'https://tradingview.com/x/AbCd1234/'],
    ['https://www.tradingview.com/chart/', 'https://www.tradingview.com/chart/Xy12ab/'],
  ])('keeps %s and %s apart', (a, b) => {
    expect(chartUrlKey(a)).not.toBe(chartUrlKey(b))
  })

  it('lower-cases scheme + host only and ends with exactly one slash', () => {
    expect(chartUrlKey('HTTPS://WWW.TradingView.com/x/AbCd1234?x#y')).toBe('https://www.tradingview.com/x/AbCd1234/')
  })
})

describe('snapshotPreviewUrl', () => {
  it.each([
    ['https://www.tradingview.com/x/AbCd1234/', 'https://s3.tradingview.com/snapshots/a/AbCd1234.png'],
    ['https://tradingview.com/x/Zq9/?utm=1#f', 'https://s3.tradingview.com/snapshots/z/Zq9.png'],
    ['https://www.tradingview.com/x/9abc', 'https://s3.tradingview.com/snapshots/9/9abc.png'],
    ['https://www.tradingview.com/chart/Xy12ab/', null],
    ['https://www.tradingview.com/chart', null],
    ['not a link', null],
  ])('%s → %s', (url, expected) => {
    expect(snapshotPreviewUrl(url)).toBe(expected)
  })
})

describe('linkErrors', () => {
  it('flags the later duplicate only, ignoring query and fragment', () => {
    const first = newLinkRow('https://www.tradingview.com/x/AbCd1234/')
    const other = newLinkRow('https://www.tradingview.com/x/Other1/', 'after')
    const dupSlash = newLinkRow('https://www.tradingview.com/x/AbCd1234')
    const dupQuery = newLinkRow('https://www.tradingview.com/x/AbCd1234/?again#f')
    expect(linkErrors([first, other, dupSlash, dupQuery])).toEqual({
      [dupSlash.rowId]: uk.describe.links.duplicate,
      [dupQuery.rowId]: uk.describe.links.duplicate,
    })
  })

  it('marks invalid URLs and ignores blank rows', () => {
    const bad = newLinkRow('https://www.tradingview.com/X/AbCd1234/')
    const blank = newLinkRow('   ')
    expect(linkErrors([bad, blank])).toEqual({ [bad.rowId]: uk.describe.links.invalid })
  })

  it('does not count an invalid row as the first occurrence', () => {
    const bad = newLinkRow('https://www.tradingview.com/x/AbCd1234//')
    const good = newLinkRow('https://www.tradingview.com/x/AbCd1234/')
    expect(linkErrors([bad, good])).toEqual({ [bad.rowId]: uk.describe.links.invalid })
  })

  it('trims surrounding whitespace before validating', () => {
    expect(linkErrors([newLinkRow('  https://www.tradingview.com/x/AbCd1234/  ')])).toEqual({})
  })
})

describe('hasBeforeLink and limits', () => {
  it('needs a filled before link', () => {
    expect(hasBeforeLink([newLinkRow('https://www.tradingview.com/x/A1/', 'after')])).toBe(false)
    expect(hasBeforeLink([newLinkRow('  ', 'before')])).toBe(false)
    expect(hasBeforeLink([newLinkRow('https://www.tradingview.com/x/A1/', 'before')])).toBe(true)
  })

  it('caps the editor at 10 links (contract: 0–10 items)', () => {
    expect(MAX_CHART_LINKS).toBe(10)
  })

  it('gives every new row a unique id', () => {
    expect(newLinkRow().rowId).not.toBe(newLinkRow().rowId)
  })
})

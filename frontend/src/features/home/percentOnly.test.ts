import { describe, expect, it } from 'vitest'

// «Головна» shows percentages only (owner 2026-11-27): no Home component formats money.
const sources = import.meta.glob(['./*.ts', './*.tsx', '../../pages/HomePage.tsx', '!./*.test.ts', '!./*.test.tsx', '!./home.fixture.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

describe('Home is percent only', () => {
  it('scans the Home sources', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(10)
  })

  it.each(Object.entries(sources))('%s never uses the USD formatter', (_path, text) => {
    expect(text).not.toMatch(/formatUsd|formatMoney|formatSignedMoney/)
  })
})

import { describe, expect, it } from 'vitest'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { inInbox } from './api'

describe('M8-01 inInbox', () => {
  const excluded = { excluded_from_stats: true, excluded_reason: 'тест', excluded_at: '2026-11-18T10:00:00Z' }

  it('keeps counted trades and drops excluded ones that only need a description', () => {
    expect(inInbox(fixtureTrade({ status: 'needs_description' }))).toBe(true)
    expect(inInbox(fixtureTrade({ status: 'needs_description', ...excluded }))).toBe(false)
    expect(inInbox(fixtureTrade({ status: 'draft', ...excluded }))).toBe(false)
  })

  it('still asks for the initial SL of an excluded trade (risk rules need it)', () => {
    expect(inInbox(fixtureTrade({ status: 'needs_sl', ...excluded }))).toBe(true)
  })
})

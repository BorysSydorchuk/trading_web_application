import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { aiKeyChip, aiKeyStateHint, aiKeyStateText, knownAiKeyState } from './keyState'

const k = uk.aiKey

describe('knownAiKeyState', () => {
  it('accepts every documented state', () => {
    for (const state of ['ok', 'invalid_key', 'not_configured', 'unreachable', 'checking']) {
      expect(knownAiKeyState(state)).toBe(state)
    }
  })

  it('returns null for a missing (older backend) or unknown state', () => {
    expect(knownAiKeyState(undefined)).toBeNull()
    expect(knownAiKeyState(null)).toBeNull()
    expect(knownAiKeyState('rate_limited')).toBeNull()
    expect(knownAiKeyState(1)).toBeNull()
  })
})

describe('aiKeyChip', () => {
  it('maps the problem states to the status bar texts with a hint', () => {
    expect(aiKeyChip('invalid_key')).toEqual({ text: 'AI: ключ недійсний', hint: k.chip.invalid_keyHint })
    expect(aiKeyChip('not_configured')).toEqual({ text: 'AI: ключ не задано', hint: k.chip.not_configuredHint })
    expect(aiKeyChip('unreachable')).toEqual({ text: 'AI: немає звʼязку', hint: k.chip.unreachableHint })
  })

  it('tells how to fix a missing or invalid key', () => {
    expect(aiKeyChip('invalid_key')?.hint).toContain('ANTHROPIC_API_KEY')
    expect(aiKeyChip('not_configured')?.hint).toBe(
      'Вкажіть ANTHROPIC_API_KEY у .env і перезапустіть застосунок',
    )
  })

  it('shows no chip for ok, checking, missing or unknown states', () => {
    for (const state of ['ok', 'checking', undefined, null, 'something_new']) {
      expect(aiKeyChip(state)).toBeNull()
    }
  })
})

describe('aiKeyStateText', () => {
  it('has a Ukrainian text for every state', () => {
    expect(aiKeyStateText('ok')).toBe('працює')
    expect(aiKeyStateText('checking')).toBe('перевіряється…')
    expect(aiKeyStateText('invalid_key')).toBe(k.states.invalid_key)
    expect(aiKeyStateText('not_configured')).toBe(k.states.not_configured)
    expect(aiKeyStateText('unreachable')).toBe(k.states.unreachable)
  })

  it('returns null for an unknown state', () => {
    expect(aiKeyStateText(undefined)).toBeNull()
    expect(aiKeyStateText('nope')).toBeNull()
  })
})

describe('aiKeyStateHint', () => {
  it('gives a hint only for the problem states', () => {
    expect(aiKeyStateHint('invalid_key')).toEqual(k.hints.invalid_key)
    expect(aiKeyStateHint('not_configured')).toEqual(k.hints.not_configured)
    expect(aiKeyStateHint('unreachable')).toEqual(k.hints.unreachable)
    expect(aiKeyStateHint('ok')).toBeNull()
    expect(aiKeyStateHint('checking')).toBeNull()
    expect(aiKeyStateHint(undefined)).toBeNull()
  })
})

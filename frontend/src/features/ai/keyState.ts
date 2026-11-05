import { uk } from '@/i18n/uk'

/** docs/api.md "AI key status (M3)". */
export const AI_KEY_STATES = ['ok', 'invalid_key', 'not_configured', 'unreachable', 'checking'] as const
export type AiKeyState = (typeof AI_KEY_STATES)[number]

export type { AiKeyStatus } from '@/api/health'

/** Known state, or null when missing (older backend) or unknown: the UI then shows nothing. */
export function knownAiKeyState(state: unknown): AiKeyState | null {
  return typeof state === 'string' && (AI_KEY_STATES as readonly string[]).includes(state)
    ? (state as AiKeyState)
    : null
}

export interface AiKeyChipView {
  text: string
  hint: string
}

/** Status bar chip: only for a problem (not for ok / checking / unknown). */
export function aiKeyChip(state: unknown): AiKeyChipView | null {
  const chip = uk.aiKey.chip
  switch (knownAiKeyState(state)) {
    case 'invalid_key':
      return { text: chip.invalid_key, hint: chip.invalid_keyHint }
    case 'not_configured':
      return { text: chip.not_configured, hint: chip.not_configuredHint }
    case 'unreachable':
      return { text: chip.unreachable, hint: chip.unreachableHint }
    default:
      return null
  }
}

/** Settings → AI: the key state in words, or null when the state is unknown. */
export function aiKeyStateText(state: unknown): string | null {
  const known = knownAiKeyState(state)
  return known ? uk.aiKey.states[known] : null
}

export interface AiKeyHint {
  title: string
  text: string
}

/** Settings hint (what to do), or null when nothing is to be done or the state is unknown. */
export function aiKeyStateHint(state: unknown): AiKeyHint | null {
  const known = knownAiKeyState(state)
  if (known === 'invalid_key' || known === 'not_configured' || known === 'unreachable') {
    return uk.aiKey.hints[known]
  }
  return null
}

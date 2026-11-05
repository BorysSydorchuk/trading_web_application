/** Maps POST/PUT /api/bias/notes errors to the editor (docs/api.md M4, 422 `entries.<i>.<field>`). */
import { isApiError } from '@/api/client'
import { uk } from '@/i18n/uk'
import type { BuiltEntries, CardErrors } from './formModel'

export interface BiasSaveErrors {
  kind: string | null
  periodDate: string | null
  rawText: string | null
  /** Symbol → errors on its card. */
  cards: Readonly<Record<string, CardErrors>>
  /** The server rejected something the form cannot point at. */
  general: boolean
  /** 409 bias_note_exists: id of the note that already has this kind + period. */
  existingId: number | null
}

export const NO_BIAS_ERRORS: BiasSaveErrors = {
  kind: null,
  periodDate: null,
  rawText: null,
  cards: {},
  general: false,
  existingId: null,
}

const ENTRY_PATH_RE = /^entries\.(\d+)\.(direction|key_levels|narrative|confidence|symbol|chart_links)(?:\.(\d+)\.url)?$/
const REJECTED = uk.describe.form.serverRejected

function existingIdOf(details: Record<string, unknown> | null): number | null {
  const id = details?.id
  return typeof id === 'number' && Number.isSafeInteger(id) ? id : null
}

function cardMessage(field: string, linkIndex: string | undefined): string {
  if (field === 'symbol') return uk.bias.editor.symbolRejected
  if (field === 'chart_links' && linkIndex === undefined) return uk.describe.links.serverRejected
  return REJECTED
}

function addCardError(cards: Record<string, CardErrors>, symbol: string, update: (card: CardErrors) => CardErrors) {
  cards[symbol] = update(cards[symbol] ?? { fields: {}, links: {} })
}

/** Points one `entries.<i>…` path at its card; false when it cannot (unknown index or field). */
function mapEntryPath(path: string, sent: BuiltEntries['sent'], cards: Record<string, CardErrors>): boolean {
  const match = ENTRY_PATH_RE.exec(path)
  const target = match ? sent[Number(match[1])] : undefined
  if (!match || !target) return false
  const field = match[2] ?? ''
  const linkIndex = match[3]
  if (linkIndex !== undefined) {
    const rowId = target.linkRows[Number(linkIndex)]
    if (!rowId) return false
    addCardError(cards, target.symbol, (card) => ({ ...card, links: { ...card.links, [rowId]: uk.describe.links.serverRejected } }))
    return true
  }
  addCardError(cards, target.symbol, (card) => ({ ...card, fields: { ...card.fields, [field]: cardMessage(field, linkIndex) } }))
  return true
}

function validationErrors(details: Record<string, unknown> | null, sent: BuiltEntries['sent']): BiasSaveErrors {
  const paths = details?.fields
  if (typeof paths !== 'object' || paths === null) return { ...NO_BIAS_ERRORS, general: true }
  const result = { ...NO_BIAS_ERRORS }
  const cards: Record<string, CardErrors> = {}
  for (const path of Object.keys(paths)) {
    if (path === 'kind') result.kind = REJECTED
    else if (path === 'period_date') result.periodDate = REJECTED
    else if (path === 'raw_text') result.rawText = uk.bias.editor.rawTextRejected
    else if (!mapEntryPath(path, sent, cards)) result.general = true
  }
  return { ...result, cards }
}

export function mapBiasSaveError(error: unknown, sent: BuiltEntries['sent']): BiasSaveErrors {
  if (!isApiError(error)) return NO_BIAS_ERRORS
  if (error.code === 'bias_note_exists') return { ...NO_BIAS_ERRORS, existingId: existingIdOf(error.details) }
  if (error.code === 'validation_error') return validationErrors(error.details, sent)
  return NO_BIAS_ERRORS
}

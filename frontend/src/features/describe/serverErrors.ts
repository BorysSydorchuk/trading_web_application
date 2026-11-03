/** Maps PUT /api/trades/{id}/journal errors to the form (docs/api.md "Journal save"). */
import { isApiError } from '@/api/client'
import { uk } from '@/i18n/uk'

export interface SaveErrors {
  /** YAML key → message (from `details.fields["fields.<key>"]`). */
  fields: Readonly<Record<string, string>>
  /** Index in the sent chart_links list → message. */
  links: Readonly<Record<number, string>>
  rawText: string | null
  /** The server rejected something the form cannot point at. */
  general: boolean
  /** `journal_incomplete` details.missing (null for other errors). */
  missing: readonly string[] | null
}

export const NO_SAVE_ERRORS: SaveErrors = { fields: {}, links: {}, rawText: null, general: false, missing: null }

const LINK_PATH_RE = /^chart_links\.(\d+)\.(url|kind)$/
const FIELD_PATH_RE = /^fields\.(.+)$/

function missingList(details: Record<string, unknown> | null): string[] {
  const missing = details?.missing
  return Array.isArray(missing) ? missing.filter((key): key is string => typeof key === 'string') : []
}

function validationErrors(details: Record<string, unknown> | null, rendered: ReadonlySet<string>): SaveErrors {
  const fields: Record<string, string> = {}
  const links: Record<number, string> = {}
  let rawText: string | null = null
  let general = false
  const paths = details?.fields
  if (typeof paths !== 'object' || paths === null) return { ...NO_SAVE_ERRORS, general: true }

  for (const path of Object.keys(paths)) {
    const link = LINK_PATH_RE.exec(path)
    const field = FIELD_PATH_RE.exec(path)
    if (link) links[Number(link[1])] = link[2] === 'url' ? uk.describe.links.serverRejected : uk.describe.links.kindRejected
    // A key without a visible control (unknown, or a hidden text_key) cannot show its error: general message.
    else if (field?.[1] && rendered.has(field[1])) fields[field[1]] = uk.describe.form.serverRejected
    else if (path === 'raw_text') rawText = uk.describe.input.rawTextRejected
    // `chart_links` alone = more than 10 links (the editor already caps at 10): general message.
    else general = true
  }
  return { fields, links, rawText, general, missing: null }
}

/** `rendered`: keys that have a visible control (formModel.renderedKeys). */
export function mapSaveError(error: unknown, rendered: ReadonlySet<string>): SaveErrors {
  if (!isApiError(error)) return NO_SAVE_ERRORS
  if (error.code === 'journal_incomplete') return { ...NO_SAVE_ERRORS, missing: missingList(error.details) }
  if (error.code === 'validation_error') return validationErrors(error.details, rendered)
  return NO_SAVE_ERRORS
}

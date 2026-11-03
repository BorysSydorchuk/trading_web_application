/** Errors from the last PUT .../journal, cleared field by field as the user edits. */
import { useState } from 'react'
import { NO_SAVE_ERRORS, mapSaveError, type SaveErrors } from './serverErrors'

/** What was sent, so errors can be pointed back at the form (link index → row, visible keys). */
export interface SaveContext {
  sentRowIds: readonly string[]
  rendered: ReadonlySet<string>
}

function withoutKey<T>(record: Readonly<Record<string, T>>, key: string): Readonly<Record<string, T>> {
  if (!Object.hasOwn(record, key)) return record
  return Object.fromEntries(Object.entries(record).filter(([k]) => k !== key))
}

function withoutMissing(errors: SaveErrors, key: string): SaveErrors {
  return { ...errors, missing: errors.missing?.filter((k) => k !== key) ?? null }
}

export function useSaveErrors() {
  const [saveErrors, setSaveErrors] = useState<SaveErrors>(NO_SAVE_ERRORS)
  const [linkErrorsByRow, setLinkErrorsByRow] = useState<Readonly<Record<string, string>>>({})

  function clearField(key: string) {
    setSaveErrors((prev) => withoutMissing({ ...prev, fields: withoutKey(prev.fields, key) }, key))
  }

  function clearLinks() {
    setLinkErrorsByRow({})
    setSaveErrors((prev) => withoutMissing(prev, 'chart_links'))
  }

  function clearRawText() {
    setSaveErrors((prev) => (prev.rawText ? { ...prev, rawText: null } : prev))
  }

  function handleSaveError(error: unknown, context: SaveContext) {
    const mapped = mapSaveError(error, context.rendered)
    setSaveErrors(mapped)
    const byRow: Record<string, string> = {}
    for (const [index, message] of Object.entries(mapped.links)) {
      const rowId = context.sentRowIds[Number(index)]
      if (rowId) byRow[rowId] = message
    }
    setLinkErrorsByRow(byRow)
  }

  return { saveErrors, linkErrorsByRow, clearField, clearLinks, clearRawText, handleSaveError }
}

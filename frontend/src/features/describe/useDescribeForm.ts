/** State of the Describe form: values, AI markers, chart links, raw text and save errors. */
import { useMemo, useState } from 'react'
import type { JournalField, JournalValue, TradeDetail } from '@/features/trades/types'
import { mergeExtraction } from './aiMerge'
import { filledLinks, isLinkKind, linkErrors, newLinkRow, type LinkDraft } from './chartLinks'
import {
  aiFilledForSave,
  buildFields,
  initialValues,
  intFieldErrors,
  missingKeys,
  renderedKeys,
  type FormValues,
} from './formModel'
import type { ExtractResult, JournalInput } from './types'
import { useSaveErrors, type SaveContext } from './useSaveErrors'

interface EditState {
  values: FormValues
  aiFilled: ReadonlySet<string>
  /** Keys filled by the last extraction (null before the first one). */
  lastApplied: number | null
}

function initialLinks(trade: TradeDetail): LinkDraft[] {
  return trade.chart_links.map((link) =>
    newLinkRow(link.url, isLinkKind(link.kind) ? link.kind : 'before', link.preview_url),
  )
}

/** What the user can change; compared with the start state for the unsaved-changes warning. */
function snapshot(fields: readonly JournalField[], values: FormValues, links: readonly LinkDraft[], rawText: string) {
  return JSON.stringify({
    fields: buildFields(fields, values),
    links: filledLinks(links).map((link) => [link.url.trim(), link.kind]),
    rawText: rawText.trim(),
  })
}

/** Values and AI markers in one state, so a late extraction merges into the latest input. */
function useJournalValues(trade: TradeDetail, fields: readonly JournalField[]) {
  const [stored] = useState<FormValues>(() => initialValues(fields, trade.journal))
  const [edit, setEdit] = useState<EditState>(() => ({
    values: stored,
    aiFilled: new Set(trade.ai_filled_fields),
    lastApplied: null,
  }))

  /** Editing a field removes its AI marker. */
  function setValue(key: string, value: JournalValue) {
    setEdit((prev) => ({
      ...prev,
      values: { ...prev.values, [key]: value },
      aiFilled: prev.aiFilled.has(key) ? new Set([...prev.aiFilled].filter((k) => k !== key)) : prev.aiFilled,
    }))
  }

  /** Rule in aiMerge.ts. */
  function mergeResult(result: ExtractResult) {
    setEdit((prev) => {
      const merged = mergeExtraction(fields, prev.values, prev.aiFilled, result)
      return { values: merged.values, aiFilled: merged.aiFilled, lastApplied: merged.applied.length }
    })
  }

  return { stored, ...edit, setValue, mergeResult }
}

export function useDescribeForm(trade: TradeDetail, fields: readonly JournalField[]) {
  const journal = useJournalValues(trade, fields)
  const errors = useSaveErrors()
  const [links, setLinksState] = useState<LinkDraft[]>(() => initialLinks(trade))
  const [rawText, setRawTextState] = useState(trade.raw_text ?? '')
  // Missing fields are highlighted once there is something to check against (PRD 6.5).
  const [showMissing, setShowMissing] = useState(trade.status === 'draft' || trade.status === 'complete')
  const [initialSnapshot] = useState(() => snapshot(fields, journal.stored, links, rawText))
  const { values, aiFilled } = journal

  const localMissing = useMemo(() => missingKeys(fields, values, links), [fields, values, links])
  const serverMissing = errors.saveErrors.missing
  const missing = useMemo(() => new Set([...localMissing, ...(serverMissing ?? [])]), [localMissing, serverMissing])
  const clientLinkErrors = useMemo(() => linkErrors(links), [links])
  const intErrors = useMemo(() => intFieldErrors(fields, values), [fields, values])

  /** PUT body plus what is needed to point server errors back at the form. */
  function buildInput(complete: boolean): { input: JournalInput; context: SaveContext } {
    const payload = buildFields(fields, values)
    const sent = filledLinks(links)
    const input: JournalInput = {
      fields: payload,
      chart_links: sent.map((link) => ({ url: link.url.trim(), kind: link.kind })),
      raw_text: rawText.trim() === '' ? null : rawText,
      ai_filled_fields: aiFilledForSave(aiFilled, payload),
      complete,
    }
    return { input, context: { sentRowIds: sent.map((link) => link.rowId), rendered: renderedKeys(fields, values) } }
  }

  return {
    stored: journal.stored,
    values,
    aiFilled,
    lastApplied: journal.lastApplied,
    links,
    rawText,
    dirty: snapshot(fields, values, links, rawText) !== initialSnapshot,
    missing,
    localMissing,
    showMissing,
    fieldErrors: { ...errors.saveErrors.fields, ...intErrors },
    linkErrors: { ...errors.linkErrorsByRow, ...clientLinkErrors },
    hasClientErrors: Object.keys(clientLinkErrors).length > 0 || Object.keys(intErrors).length > 0,
    saveErrors: errors.saveErrors,
    setShowMissing,
    setField: (key: string, value: JournalValue) => {
      journal.setValue(key, value)
      errors.clearField(key)
    },
    setLinks: (next: LinkDraft[]) => {
      setLinksState(next)
      errors.clearLinks()
    },
    setRawText: (text: string) => {
      setRawTextState(text)
      errors.clearRawText()
    },
    applyExtraction: (result: ExtractResult) => {
      journal.mergeResult(result)
      setShowMissing(true)
    },
    buildInput,
    handleSaveError: errors.handleSaveError,
  }
}

export type DescribeForm = ReturnType<typeof useDescribeForm>

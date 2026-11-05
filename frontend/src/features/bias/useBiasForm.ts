/** State of the bias note editor: kind/date, text, one card per symbol, AI markers, errors. */
import { useMemo, useState } from 'react'
import type { LinkDraft } from '@/features/describe/chartLinks'
import { appendTranscript } from '@/features/voice/notesModel'
import { isIsoDate } from '@/lib/time'
import {
  buildEntries,
  clearDraft,
  clientCardErrors,
  initialDrafts,
  mergeBiasExtraction,
  setDraftValue,
  snapshot,
  type BuiltEntries,
  type CardErrors,
  type EntryDraft,
  type EntryValues,
} from './formModel'
import { normalizePeriod } from './period'
import { mapBiasSaveError, NO_BIAS_ERRORS, type BiasSaveErrors } from './serverErrors'
import type { BiasAiField, BiasExtractResult, BiasKind, BiasNote, BiasNoteInput } from './types'

export interface BiasFormStart {
  symbols: readonly string[]
  note: BiasNote | null
  kind: BiasKind
  date: string
}

const NO_CARD_ERRORS: CardErrors = { fields: {}, links: {} }

function mergeCardErrors(server: CardErrors | undefined, client: CardErrors | undefined, withDirection: boolean): CardErrors {
  const clientFields = withDirection ? (client?.fields ?? {}) : {}
  return {
    fields: { ...server?.fields, ...clientFields },
    links: { ...server?.links, ...client?.links },
  }
}

function withoutCardPart(errors: BiasSaveErrors, symbol: string, part: 'links' | BiasAiField): BiasSaveErrors {
  const card = errors.cards[symbol]
  if (!card) return errors
  const next: CardErrors =
    part === 'links'
      ? { fields: { ...card.fields, chart_links: undefined }, links: {} }
      : { ...card, fields: { ...card.fields, [part]: undefined } }
  return { ...errors, cards: { ...errors.cards, [symbol]: next } }
}

interface DraftState {
  drafts: EntryDraft[]
  /** Fields filled by the last extraction (null before the first one). */
  lastApplied: number | null
}

/** Cards and the extraction count in one state, so a late extraction merges into the latest input. */
function useDrafts(start: BiasFormStart) {
  const [state, setState] = useState<DraftState>(() => ({
    drafts: initialDrafts(start.symbols, start.note),
    lastApplied: null,
  }))

  function update(symbol: string, change: (draft: EntryDraft) => EntryDraft) {
    setState((prev) => ({
      ...prev,
      drafts: prev.drafts.map((draft) => (draft.symbol === symbol ? change(draft) : draft)),
    }))
  }

  function applyExtraction(result: BiasExtractResult) {
    setState((prev) => {
      const merged = mergeBiasExtraction(prev.drafts, result)
      return { drafts: merged.drafts, lastApplied: merged.applied }
    })
  }

  return { drafts: state.drafts, lastApplied: state.lastApplied, update, applyExtraction }
}

export function useBiasForm(start: BiasFormStart) {
  const [kind, setKindState] = useState<BiasKind>(start.kind)
  const [date, setDateState] = useState(start.date)
  const [rawText, setRawTextState] = useState(start.note?.raw_text ?? '')
  const cards = useDrafts(start)
  const [serverErrors, setServerErrors] = useState<BiasSaveErrors>(NO_BIAS_ERRORS)
  const [attempted, setAttempted] = useState(false)
  const [savedSnapshot, setSavedSnapshot] = useState(() =>
    snapshot(start.kind, normalizePeriod(start.kind, start.date), rawText, cards.drafts),
  )

  const dateValid = isIsoDate(date)
  const periodDate = dateValid ? normalizePeriod(kind, date) : ''
  const clientErrors = useMemo(() => clientCardErrors(cards.drafts), [cards.drafts])

  function cardErrors(symbol: string): CardErrors {
    const server = serverErrors.cards[symbol]
    const client = clientErrors[symbol]
    if (!server && !client) return NO_CARD_ERRORS
    return mergeCardErrors(server, client, attempted)
  }

  function buildInput(): { input: BiasNoteInput; sent: BuiltEntries['sent'] } {
    const built = buildEntries(cards.drafts)
    return {
      input: { kind, period_date: periodDate, raw_text: rawText.trim() === '' ? null : rawText, entries: built.entries },
      sent: built.sent,
    }
  }

  return {
    kind,
    date,
    dateValid,
    periodDate,
    rawText,
    drafts: cards.drafts,
    lastApplied: cards.lastApplied,
    dirty: snapshot(kind, periodDate, rawText, cards.drafts) !== savedSnapshot,
    /** After a save that stays on the page: the saved state is the new baseline of the guard. */
    markSaved: () => setSavedSnapshot(snapshot(kind, periodDate, rawText, cards.drafts)),
    serverErrors,
    cardErrors,
    dateError: attempted && !dateValid,
    hasClientErrors: Object.keys(clientErrors).length > 0 || !dateValid,
    setAttempted,
    setKind: (next: BiasKind) => {
      setKindState(next)
      setServerErrors((prev) => ({ ...prev, kind: null, periodDate: null, existingId: null }))
    },
    setDate: (next: string) => {
      setDateState(next)
      setServerErrors((prev) => ({ ...prev, periodDate: null, existingId: null }))
    },
    setRawText: (text: string) => {
      setRawTextState(text)
      setServerErrors((prev) => (prev.rawText ? { ...prev, rawText: null } : prev))
    },
    /** A voice transcript goes after the current text (blank line between); updater, so two at once both land. */
    appendTranscript: (transcript: string) => {
      setRawTextState((prev) => appendTranscript(prev, transcript))
      setServerErrors((prev) => (prev.rawText ? { ...prev, rawText: null } : prev))
    },
    setValue: <K extends BiasAiField>(symbol: string, key: K, value: EntryValues[K]) => {
      cards.update(symbol, (draft) => setDraftValue(draft, key, value))
      setServerErrors((prev) => withoutCardPart(prev, symbol, key))
    },
    setLinks: (symbol: string, links: LinkDraft[]) => {
      cards.update(symbol, (draft) => ({ ...draft, links }))
      setServerErrors((prev) => withoutCardPart(prev, symbol, 'links'))
    },
    clearCard: (symbol: string) => {
      cards.update(symbol, clearDraft)
      setServerErrors((prev) => ({ ...prev, cards: { ...prev.cards, [symbol]: NO_CARD_ERRORS } }))
    },
    applyExtraction: cards.applyExtraction,
    buildInput,
    handleSaveError: (error: unknown, sent: BuiltEntries['sent']) => setServerErrors(mapBiasSaveError(error, sent)),
    showExisting: (id: number | null) => setServerErrors((prev) => ({ ...prev, existingId: id })),
  }
}

export type BiasForm = ReturnType<typeof useBiasForm>

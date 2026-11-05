import { useRef, useState } from 'react'
import { Loader2, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DescriptionInput } from '@/features/describe/DescriptionInput'
import { AiBadge } from '@/features/describe/FieldControls'
import { UnsavedChangesGuard } from '@/features/describe/UnsavedChangesGuard'
import type { AudioNote } from '@/features/voice/types'
import { VoiceNotes } from '@/features/voice/VoiceNotes'
import { uk } from '@/i18n/uk'
import { useUploadBiasAudio } from './api'
import { BiasEntryCard } from './BiasEntryCard'
import { BiasPeriodFields } from './BiasPeriodFields'
import { DeleteBiasDialog } from './DeleteBiasDialog'
import type { BiasKind, BiasNote } from './types'
import { useBiasActions, type BiasActions } from './useBiasActions'
import { useBiasForm, type BiasForm } from './useBiasForm'

const e = uk.bias.editor
const NO_NOTES: readonly AudioNote[] = []
const VOICE_LABELS = { title: e.voiceTitle, listLabel: e.voiceListLabel, hint: e.voiceHint }

export interface BiasEditorProps {
  symbols: readonly string[]
  /** The saved note (edit) or null (new). */
  note: BiasNote | null
  kind: BiasKind
  date: string
  /** The editor created its note (voice upload or a save that stays): the page keeps this editor. */
  onCreated: (note: BiasNote) => void
}

/** Bias note editor (PRD 6.6): kind + date, text and voice, "Заповнити з тексту", one card per symbol. */
export function BiasEditor({ symbols, note, kind, date, onCreated }: BiasEditorProps) {
  const form = useBiasForm({ symbols, note, kind, date })
  const [unsentRecording, setUnsentRecordingState] = useState(false)
  // Read when a save lands (after this render), so a ref next to the state.
  const unsentRecordingRef = useRef(false)
  const actions = useBiasActions({ form, initialNoteId: note?.id ?? null, unsentRecordingRef, onCreated })
  const upload = useUploadBiasAudio(actions.ensureNoteId)

  function setUnsentRecording(unsent: boolean) {
    unsentRecordingRef.current = unsent
    setUnsentRecordingState(unsent)
  }

  return (
    <div data-bias-editor className="flex flex-col gap-4">
      <section aria-label={e.period} className="flex flex-col gap-3 rounded-lg border p-4">
        <BiasPeriodFields form={form} noteId={actions.noteId} />
      </section>
      <div className="flex flex-col gap-4 rounded-lg border p-4">
        <DescriptionInput
          label={e.rawTextLabel}
          placeholder={e.rawTextPlaceholder}
          rawText={form.rawText}
          onRawText={form.setRawText}
          rawTextError={form.serverErrors.rawText}
          onExtract={actions.runExtract}
          extracting={actions.extract.isPending}
          startedAt={actions.extractStartedAt}
          extractError={actions.extract.isError ? actions.extract.error : null}
          lastApplied={form.lastApplied}
          voice={
            <VoiceNotes
              initialNotes={note?.audio_notes ?? NO_NOTES}
              upload={upload}
              onTranscript={form.appendTranscript}
              onUnsentChange={setUnsentRecording}
              labels={VOICE_LABELS}
            />
          }
        />
      </div>
      <Cards form={form} />
      <SaveBar form={form} actions={actions} />
      {/* A recording that only exists in the browser is lost on leaving, like unsaved edits. */}
      <UnsavedChangesGuard
        dirty={form.dirty || unsentRecording}
        allowLeaveRef={actions.allowLeaveRef}
        description={e.unsaved}
      />
    </div>
  )
}

function Cards({ form }: { form: BiasForm }) {
  return (
    <section aria-label={e.symbols} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <h2 className="text-sm font-semibold text-foreground">{e.symbols}</h2>
        <span>
          <span className="text-foreground">{uk.common.requiredMark}</span> {e.symbolsHint}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <AiBadge /> {uk.describe.form.aiLegend}
        </span>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {form.drafts.map((draft) => (
          <BiasEntryCard
            key={draft.symbol}
            draft={draft}
            errors={form.cardErrors(draft.symbol)}
            onValue={(key, value) => form.setValue(draft.symbol, key, value)}
            onLinks={(links) => form.setLinks(draft.symbol, links)}
            onClear={() => form.clearCard(draft.symbol)}
          />
        ))}
      </div>
    </section>
  )
}

/** Sticky footer: general error, Видалити (saved note), Зберегти. */
function SaveBar({ form, actions }: { form: BiasForm; actions: BiasActions }) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const saving = actions.save.isPending
  return (
    <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 rounded-lg border bg-background/95 px-4 py-3 backdrop-blur">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs">
        {form.serverErrors.general && (
          <p role="alert" className="text-destructive">
            {e.formError}
          </p>
        )}
      </div>
      {actions.noteId !== null && (
        <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmOpen(true)} disabled={saving}>
          <Trash2 aria-hidden />
          {e.delete}
        </Button>
      )}
      <Button type="button" size="sm" onClick={actions.submit} disabled={saving}>
        {saving && <Loader2 className="animate-spin" aria-hidden />}
        {saving ? e.saving : e.save}
      </Button>
      <DeleteBiasDialog
        open={confirmOpen}
        deleting={actions.remove.isPending}
        onOpenChange={setConfirmOpen}
        onConfirm={() => actions.deleteNote(() => setConfirmOpen(false))}
      />
    </div>
  )
}

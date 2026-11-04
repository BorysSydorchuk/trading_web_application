import { useMemo, useRef, useState } from 'react'
import { Info, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { JournalField, TradeDetail } from '@/features/trades/types'
import type { AudioNote } from '@/features/voice/types'
import { uk } from '@/i18n/uk'
import { ChartLinksEditor } from './ChartLinksEditor'
import { DescribeVoice } from './DescribeVoice'
import { DescriptionInput } from './DescriptionInput'
import { AiBadge } from './FieldControls'
import { fieldsForTrade, keyLabels, linksField, stillEmptyKeys } from './formModel'
import { JournalForm } from './JournalForm'
import { TradeSummary } from './TradeSummary'
import { UnsavedChangesGuard } from './UnsavedChangesGuard'
import { useDescribeActions } from './useDescribeActions'
import { useDescribeForm, type DescribeForm } from './useDescribeForm'

const t = uk.describe
/** A backend from before M3 sends no `audio_notes`. */
const NO_NOTES: readonly AudioNote[] = []
/** A backend from before M3-07 sends no `missing_new_fields`. */
const NO_NEW_FIELDS: readonly string[] = []

interface DescribeEditorProps {
  trade: TradeDetail
  fields: readonly JournalField[]
}

/** Describe screen body (PRD 6.5): auto data left, text + links + generated form right. */
export function DescribeEditor({ trade, fields: allFields }: DescribeEditorProps) {
  // Fields made required after this trade closed are optional for it (docs/api.md M3).
  const newFields = trade.missing_new_fields ?? NO_NEW_FIELDS
  const fields = useMemo(() => fieldsForTrade(allFields, newFields), [allFields, newFields])
  const form = useDescribeForm(trade, fields)
  const [unsentRecording, setUnsentRecordingState] = useState(false)
  // Read when a save lands (after this render), so a ref next to the state.
  const unsentRecordingRef = useRef(false)
  const actions = useDescribeActions(trade.id, form, unsentRecordingRef)
  const { save, extract } = actions
  const links = linksField(fields)

  function setUnsentRecording(unsent: boolean) {
    unsentRecordingRef.current = unsent
    setUnsentRecordingState(unsent)
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(260px,340px)_minmax(0,1fr)]">
      <div className="lg:sticky lg:top-4">
        <TradeSummary trade={trade} />
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <section className="flex flex-col gap-4 rounded-lg border p-4" aria-label={t.input.title}>
          <DescriptionInput
            rawText={form.rawText}
            onRawText={form.setRawText}
            rawTextError={form.saveErrors.rawText}
            onExtract={actions.runExtract}
            extracting={extract.isPending}
            startedAt={actions.extractStartedAt}
            extractError={extract.isError ? extract.error : null}
            lastApplied={form.lastApplied}
            voice={
              <DescribeVoice
                tradeId={trade.id}
                tradeNotes={trade.audio_notes ?? NO_NOTES}
                onTranscript={form.appendTranscript}
                onUnsentChange={setUnsentRecording}
              />
            }
          />
          <ChartLinksEditor
            field={links}
            links={form.links}
            errors={form.linkErrors}
            missing={form.showMissing && links !== undefined && form.missing.has(links.key)}
            onChange={form.setLinks}
          />
        </section>
        <FormSection trade={trade} fields={fields} form={form} newFields={newFields} />
        <SaveBar
          fields={fields}
          missing={form.showMissing ? [...form.missing] : []}
          general={form.saveErrors.general}
          saving={save.isPending}
          savingComplete={save.isPending && save.variables.complete}
          onSave={actions.submit}
        />
      </div>
      {/* A recording that only exists in the browser is lost on leaving, like unsaved edits. */}
      <UnsavedChangesGuard dirty={form.dirty || unsentRecording} allowLeaveRef={actions.allowLeaveRef} />
    </div>
  )
}

interface FormSectionProps extends DescribeEditorProps {
  form: DescribeForm
  newFields: readonly string[]
}

function FormSection({ trade, fields, form, newFields }: FormSectionProps) {
  const autoViolations = useMemo(
    () => new Set(trade.rule_violations.filter((v) => v.source === 'auto').map((v) => v.rule_key)),
    [trade.rule_violations],
  )
  return (
    <section className="flex flex-col gap-3 rounded-lg border p-4" aria-label={t.form.title}>
      <FormLegend />
      <NewFieldsHint fields={fields} keys={newFields} form={form} />
      <JournalForm
        fields={fields}
        values={form.values}
        stored={form.stored}
        journal={trade.journal}
        aiFilled={form.aiFilled}
        missing={form.showMissing ? form.missing : EMPTY_SET}
        errors={form.fieldErrors}
        autoViolations={autoViolations}
        onChange={form.setField}
      />
    </section>
  )
}

const EMPTY_SET: ReadonlySet<string> = new Set()

/** Neutral note (not an error): fields that became required after the trade closed and are still empty. */
interface NewFieldsHintProps {
  fields: readonly JournalField[]
  /** TradeDetail.missing_new_fields at load; keys the user has filled since are left out. */
  keys: readonly string[]
  form: DescribeForm
}

function NewFieldsHint({ fields, keys, form }: NewFieldsHintProps) {
  const labels = useMemo(() => keyLabels(fields), [fields])
  const empty = useMemo(
    () => stillEmptyKeys(fields, keys, form.values, form.links),
    [fields, keys, form.values, form.links],
  )
  if (empty.length === 0) return null
  return (
    <div role="note" className="flex gap-2 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
      <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <div className="flex flex-col gap-0.5">
        <p>
          <span className="text-foreground">{t.form.newFieldsHint}</span>{' '}
          {empty.map((key) => labels.get(key) ?? key).join(', ')}
        </p>
        <p>{t.form.newFieldsNote}</p>
      </div>
    </div>
  )
}

function FormLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <h2 className="text-sm font-semibold text-foreground">{t.form.title}</h2>
      <span>
        <span className="text-foreground">{uk.common.requiredMark}</span> {uk.common.requiredLegend}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <AiBadge /> {t.form.aiLegend}
      </span>
    </div>
  )
}

interface SaveBarProps {
  fields: readonly JournalField[]
  missing: readonly string[]
  general: boolean
  saving: boolean
  savingComplete: boolean
  onSave: (complete: boolean) => void
}

/** Sticky footer: "Не вистачає: …", draft and complete buttons. */
function SaveBar({ fields, missing, general, saving, savingComplete, onSave }: SaveBarProps) {
  const labels = useMemo(() => keyLabels(fields), [fields])
  return (
    <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-3 rounded-lg border bg-background/95 px-4 py-3 backdrop-blur">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs">
        {missing.length > 0 && (
          <p className="text-destructive">
            {t.save.missing}{' '}
            <span>{missing.map((key) => labels.get(key) ?? key).join(', ')}</span>
          </p>
        )}
        {general && (
          <p role="alert" className="text-destructive">
            {t.save.formError}
          </p>
        )}
      </div>
      <Button type="button" variant="outline" size="sm" onClick={() => onSave(false)} disabled={saving}>
        {saving && !savingComplete && <Loader2 className="animate-spin" aria-hidden />}
        {t.save.draft}
      </Button>
      <Button type="button" size="sm" onClick={() => onSave(true)} disabled={saving}>
        {savingComplete && <Loader2 className="animate-spin" aria-hidden />}
        {t.save.complete}
      </Button>
    </div>
  )
}

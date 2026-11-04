import { useMemo } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { JournalField, TradeDetail } from '@/features/trades/types'
import type { AudioNote } from '@/features/voice/types'
import { uk } from '@/i18n/uk'
import { ChartLinksEditor } from './ChartLinksEditor'
import { DescribeVoice } from './DescribeVoice'
import { DescriptionInput } from './DescriptionInput'
import { AiBadge } from './FieldControls'
import { keyLabels, linksField } from './formModel'
import { JournalForm } from './JournalForm'
import { TradeSummary } from './TradeSummary'
import { UnsavedChangesGuard } from './UnsavedChangesGuard'
import { useDescribeActions } from './useDescribeActions'
import { useDescribeForm, type DescribeForm } from './useDescribeForm'

const t = uk.describe
/** A backend from before M3 sends no `audio_notes`. */
const NO_NOTES: readonly AudioNote[] = []

interface DescribeEditorProps {
  trade: TradeDetail
  fields: readonly JournalField[]
}

/** Describe screen body (PRD 6.5): auto data left, text + links + generated form right. */
export function DescribeEditor({ trade, fields }: DescribeEditorProps) {
  const form = useDescribeForm(trade, fields)
  const actions = useDescribeActions(trade.id, form)
  const { save, extract } = actions
  const links = linksField(fields)

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
        <FormSection trade={trade} fields={fields} form={form} />
        <SaveBar
          fields={fields}
          missing={form.showMissing ? [...form.missing] : []}
          general={form.saveErrors.general}
          saving={save.isPending}
          savingComplete={save.isPending && save.variables.complete}
          onSave={actions.submit}
        />
      </div>
      <UnsavedChangesGuard dirty={form.dirty} allowLeaveRef={actions.allowLeaveRef} />
    </div>
  )
}

function FormSection({ trade, fields, form }: DescribeEditorProps & { form: DescribeForm }) {
  const autoViolations = useMemo(
    () => new Set(trade.rule_violations.filter((v) => v.source === 'auto').map((v) => v.rule_key)),
    [trade.rule_violations],
  )
  return (
    <section className="flex flex-col gap-3 rounded-lg border p-4" aria-label={t.form.title}>
      <FormLegend />
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

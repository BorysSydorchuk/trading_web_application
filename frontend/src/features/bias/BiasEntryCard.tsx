import { Eraser, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { LinkDraft } from '@/features/describe/chartLinks'
import { ChartLinksEditor } from '@/features/describe/ChartLinksEditor'
import { FieldShell, Segmented } from '@/features/describe/FieldControls'
import { fieldDomId } from '@/features/describe/formModel'
import { uk } from '@/i18n/uk'
import { biasFieldKey, isDraftEmpty, MAX_ENTRY_TEXT_LENGTH, type CardErrors, type EntryDraft, type EntryValues } from './formModel'
import { BIAS_DIRECTIONS, MAX_CONFIDENCE, MIN_CONFIDENCE, isBiasDirection, type BiasAiField } from './types'

const e = uk.bias.editor

const DIRECTION_OPTIONS = BIAS_DIRECTIONS.map((value) => ({ value, label: uk.bias.directions[value] }))
const CONFIDENCE_OPTIONS = Array.from({ length: MAX_CONFIDENCE - MIN_CONFIDENCE + 1 }, (_, i) => {
  const value = String(MIN_CONFIDENCE + i)
  return { value, label: value }
})

interface BiasEntryCardProps {
  draft: EntryDraft
  errors: CardErrors
  onValue: <K extends BiasAiField>(key: K, value: EntryValues[K]) => void
  onLinks: (links: LinkDraft[]) => void
  onClear: () => void
}

/** One symbol of the note: direction (needed to save it), levels, narrative, confidence, links. */
export function BiasEntryCard({ draft, errors, onValue, onLinks, onClear }: BiasEntryCardProps) {
  const { symbol, values, aiFilled } = draft
  const key = (field: BiasAiField | 'chart_links') => biasFieldKey(symbol, field)
  return (
    <section aria-label={e.cardLabel(symbol)} className="flex min-w-0 flex-col gap-2 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <h3 className="num text-sm font-semibold">{symbol}</h3>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto h-7 text-xs"
          aria-label={e.clearCardLabel(symbol)}
          onClick={onClear}
          disabled={!draft.known || isDraftEmpty(draft)}
        >
          <Eraser aria-hidden />
          {e.clearCard}
        </Button>
      </div>
      {!draft.known && (
        <p role="note" className="flex gap-1.5 text-xs text-muted-foreground">
          <Info className="mt-px size-3.5 shrink-0" aria-hidden />
          {e.unknownSymbol}
        </p>
      )}
      {errors.fields.symbol && (
        <p role="alert" className="text-xs text-destructive">
          {errors.fields.symbol}
        </p>
      )}
      <fieldset disabled={!draft.known} className="flex min-w-0 flex-col gap-2">
        <FieldShell
          fieldKey={key('direction')}
          label={e.fields.direction}
          required
          aiFilled={aiFilled.has('direction')}
          missing={false}
          error={errors.fields.direction ?? null}
          group
        >
          <Segmented
            id={fieldDomId(key('direction'))}
            options={DIRECTION_OPTIONS}
            value={values.direction}
            invalid={errors.fields.direction !== undefined}
            onChange={(value) => onValue('direction', isBiasDirection(value) ? value : null)}
          />
        </FieldShell>
        <FieldShell
          fieldKey={key('key_levels')}
          label={e.fields.key_levels}
          required={false}
          aiFilled={aiFilled.has('key_levels')}
          missing={false}
          error={errors.fields.key_levels ?? null}
        >
          <Input
            id={fieldDomId(key('key_levels'))}
            className="h-8 text-sm"
            maxLength={MAX_ENTRY_TEXT_LENGTH}
            placeholder={e.keyLevelsPlaceholder}
            value={values.key_levels}
            aria-invalid={errors.fields.key_levels ? true : undefined}
            onChange={(event) => onValue('key_levels', event.target.value)}
          />
        </FieldShell>
        <FieldShell
          fieldKey={key('narrative')}
          label={e.fields.narrative}
          required={false}
          aiFilled={aiFilled.has('narrative')}
          missing={false}
          error={errors.fields.narrative ?? null}
        >
          <Textarea
            id={fieldDomId(key('narrative'))}
            rows={2}
            maxLength={MAX_ENTRY_TEXT_LENGTH}
            value={values.narrative}
            aria-invalid={errors.fields.narrative ? true : undefined}
            onChange={(event) => onValue('narrative', event.target.value)}
          />
        </FieldShell>
        <FieldShell
          fieldKey={key('confidence')}
          label={e.fields.confidence}
          required={false}
          aiFilled={aiFilled.has('confidence')}
          missing={false}
          error={errors.fields.confidence ?? null}
          group
        >
          <Segmented
            id={fieldDomId(key('confidence'))}
            options={CONFIDENCE_OPTIONS}
            value={values.confidence === null ? null : String(values.confidence)}
            invalid={errors.fields.confidence !== undefined}
            mono
            onChange={(value) => onValue('confidence', value === null ? null : Number(value))}
          />
        </FieldShell>
        <ChartLinksEditor
          field={undefined}
          fieldKey={key('chart_links')}
          label={e.fields.chart_links}
          showKind={false}
          links={draft.links}
          errors={errors.links}
          missing={false}
          onChange={onLinks}
        />
        {errors.fields.chart_links && (
          <p role="alert" className="text-xs text-destructive">
            {errors.fields.chart_links}
          </p>
        )}
      </fieldset>
    </section>
  )
}

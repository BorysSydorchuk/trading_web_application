import { useId } from 'react'
import { AlertCircle, ExternalLink } from 'lucide-react'
import { Link } from 'react-router'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { useBiasNoteByPeriod } from './api'
import { formatIsoDate } from './period'
import { BIAS_KINDS, isBiasKind, type BiasKind } from './types'
import type { BiasForm } from './useBiasForm'

const e = uk.bias.editor
const LABEL = 'text-xs font-medium text-muted-foreground'

function periodNote(kind: BiasKind, periodDate: string): string | null {
  if (periodDate === '') return null
  if (kind === 'weekly') return e.weekNote(formatIsoDate(periodDate))
  if (kind === 'monthly') return e.monthNote(formatIsoDate(periodDate))
  return null
}

/** Kind select + date picker; weekly/monthly show the normalized Monday / 1st. */
export function BiasPeriodFields({ form, noteId }: { form: BiasForm; noteId: number | null }) {
  const id = useId()
  const byPeriod = useBiasNoteByPeriod(form.kind, form.periodDate, form.dateValid)
  const other = byPeriod.data && byPeriod.data.id !== noteId ? byPeriod.data.id : null
  const existingId = form.serverErrors.existingId ?? other
  const note = periodNote(form.kind, form.periodDate)
  const dateError = form.dateError ? e.dateRequired : form.serverErrors.periodDate
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-start gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${id}-kind`} className={LABEL}>
            {e.kind}
            <span className="text-foreground" aria-hidden>
              {uk.common.requiredMark}
            </span>
          </label>
          <NativeSelect
            id={`${id}-kind`}
            className="h-8 w-52 text-sm"
            wrapperClassName="w-auto"
            value={form.kind}
            aria-invalid={form.serverErrors.kind ? true : undefined}
            onChange={(event) => isBiasKind(event.target.value) && form.setKind(event.target.value)}
          >
            {BIAS_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {uk.bias.kinds[kind]}
              </option>
            ))}
          </NativeSelect>
          {form.serverErrors.kind && (
            <p role="alert" className="text-xs text-destructive">
              {form.serverErrors.kind}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${id}-date`} className={cn(LABEL, dateError && 'text-destructive')}>
            {e.date}
            <span className="text-foreground" aria-hidden>
              {uk.common.requiredMark}
            </span>
          </label>
          <Input
            id={`${id}-date`}
            type="date"
            className="num h-8 w-44 text-sm"
            value={form.date}
            required
            aria-invalid={dateError ? true : undefined}
            onChange={(event) => form.setDate(event.target.value)}
          />
          {dateError && (
            <p role="alert" className="text-xs text-destructive">
              {dateError}
            </p>
          )}
        </div>
      </div>
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      {existingId !== null && <ExistingNoteNotice id={existingId} kind={form.kind} periodDate={form.periodDate} />}
    </div>
  )
}

interface ExistingNoteNoticeProps {
  id: number
  kind: BiasKind
  periodDate: string
}

/** 409 bias_note_exists (or found ahead by by-period): one note per kind + period, link to it. */
function ExistingNoteNotice({ id, kind, periodDate }: ExistingNoteNoticeProps) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-dashed px-3 py-2 text-xs">
      <span className="flex items-center gap-1.5">
        <AlertCircle className="size-3.5 shrink-0 text-destructive" aria-hidden />
        {e.exists(uk.bias.kinds[kind], formatIsoDate(periodDate))}
      </span>
      <Link to={`/bias/${id}`} className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-foreground">
        <ExternalLink className="size-3" aria-hidden />
        {e.openExisting}
      </Link>
    </div>
  )
}

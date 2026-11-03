import { useEffect, useId, useState } from 'react'
import { AlertCircle, Info, Loader2, Mic, Sparkles } from 'lucide-react'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { MAX_RAW_TEXT_LENGTH } from './formModel'

const t = uk.describe.input
const ELAPSED_TICK_MS = 250

interface DescriptionInputProps {
  rawText: string
  onRawText: (text: string) => void
  rawTextError: string | null
  onExtract: () => void
  extracting: boolean
  /** Date.now() when the running extraction started. */
  startedAt: number | null
  extractError: unknown
  /** Keys filled by the last successful extraction (null before the first one). */
  lastApplied: number | null
}

/** Left column of the input area: free text, voice placeholder (M3), "Заповнити з тексту". */
export function DescriptionInput(props: DescriptionInputProps) {
  const { rawText, onRawText, rawTextError, onExtract, extracting } = props
  const id = useId()
  const canExtract = rawText.trim() !== '' && !extracting
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={`${id}-raw`} className="text-xs font-medium text-muted-foreground">
        {t.rawTextLabel}
      </label>
      <Textarea
        id={`${id}-raw`}
        rows={6}
        maxLength={MAX_RAW_TEXT_LENGTH}
        placeholder={t.rawTextPlaceholder}
        value={rawText}
        aria-invalid={rawTextError ? true : undefined}
        onChange={(e) => onRawText(e.target.value)}
      />
      {rawTextError && (
        <p role="alert" className="text-xs text-destructive">
          {rawTextError}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" size="sm" onClick={onExtract} disabled={!canExtract}>
          {extracting ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
          {extracting ? t.extracting : t.extract}
        </Button>
        <ExtractStatus {...props} />
      </div>
      <VoicePlaceholder />
    </div>
  )
}

function ExtractStatus({ extracting, startedAt, extractError, lastApplied }: DescriptionInputProps) {
  if (extracting && startedAt !== null) return <Elapsed startedAt={startedAt} />
  if (extractError) return <ExtractErrorNote error={extractError} />
  if (lastApplied !== null) {
    return <span className="text-xs text-muted-foreground">{t.extractDone(lastApplied)}</span>
  }
  return <span className="text-xs text-muted-foreground">{t.extractHint}</span>
}

/** Spinner text with elapsed seconds (target < 30 s, PRD 6.5). */
function Elapsed({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(startedAt)
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), ELAPSED_TICK_MS)
    return () => window.clearInterval(timer)
  }, [])
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  return (
    <span role="status" className="num text-xs text-muted-foreground">
      {t.elapsed(seconds)}
    </span>
  )
}

function ExtractErrorNote({ error }: { error: unknown }) {
  // Not an error of this trade: the key is simply not set, the manual form still works.
  if (isApiError(error) && error.code === 'ai_not_configured') {
    return (
      <p role="alert" className="flex max-w-prose items-start gap-1.5 text-xs text-muted-foreground">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>{t.aiNotConfigured}</span>
      </p>
    )
  }
  return (
    <p role="alert" className="flex max-w-prose items-start gap-1.5 text-xs text-destructive">
      <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>
        {errorText(error)} {t.manualStillWorks}
      </span>
    </p>
  )
}

/** Voice input arrives in M3; this keeps its place in the layout. */
function VoicePlaceholder() {
  return (
    <div className="flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-xs text-muted-foreground">
      <Mic className="size-3.5" aria-hidden />
      {t.voiceLater}
    </div>
  )
}

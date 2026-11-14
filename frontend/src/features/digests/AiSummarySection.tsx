import { AlertCircle, Info, Loader2, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { isApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { useAiSummary } from './api'
import type { Digest } from './types'

const t = uk.digests.ai

/** Transient AI failures reuse the shared texts; the form-oriented ones get summary-specific wording. */
const SHARED_AI_KINDS = new Set(['auth', 'rate_limit', 'overloaded', 'timeout', 'connection', 'api'])

/** Readable Ukrainian text for a failed summary call (docs/api.md: ai_not_configured / ai_error as M2). */
function aiSummaryErrorText(error: unknown): string {
  if (!isApiError(error)) return errorText(error)
  if (error.code === 'ai_not_configured') return t.notConfigured
  if (error.code !== 'ai_error') return errorText(error)
  const kind = error.details?.kind
  if (typeof kind === 'string' && SHARED_AI_KINDS.has(kind)) return errorText(error)
  if (kind === 'refusal') return t.refusal
  if (kind === 'invalid_output') return t.invalidOutput
  return t.error
}

/** «Підсумок ШІ»: always visible on a created digest; the Claude call runs only on button press. */
export function AiSummarySection({ digest }: { digest: Digest }) {
  const summary = useAiSummary()
  const hasSummary = Boolean(digest.ai_summary)

  function run() {
    summary.mutate(digest, {
      onError: (error) => {
        const id = isApiError(error) ? `digest-ai:${error.code}` : 'digest-ai:unknown'
        toast.error(aiSummaryErrorText(error), { id })
      },
    })
  }

  return (
    <section aria-labelledby="digest-ai" className="flex flex-col gap-2 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="digest-ai" className="text-sm font-semibold">
          {uk.digests.page.aiSummary}
        </h2>
        <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={run} disabled={summary.isPending}>
          {summary.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
          {summary.isPending ? t.generating : hasSummary ? t.refresh : t.generate}
        </Button>
      </div>
      {hasSummary ? (
        <p className="text-sm whitespace-pre-line">{digest.ai_summary}</p>
      ) : (
        <p className="text-sm text-muted-foreground">{t.empty}</p>
      )}
      {summary.isError && <AiSummaryErrorNote error={summary.error} />}
    </section>
  )
}

function AiSummaryErrorNote({ error }: { error: unknown }) {
  // The key is simply not set: a calm note, the digest itself works without the summary.
  const notConfigured = isApiError(error) && error.code === 'ai_not_configured'
  const Icon = notConfigured ? Info : AlertCircle
  return (
    <p
      role="alert"
      className={cn(
        'flex max-w-prose items-start gap-1.5 text-xs',
        notConfigured ? 'text-muted-foreground' : 'text-destructive',
      )}
    >
      <Icon className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{aiSummaryErrorText(error)}</span>
    </p>
  )
}

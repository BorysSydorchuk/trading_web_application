import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { formatDecimal, roundDecimal } from '@/lib/decimal'
import { useHealth } from '@/api/health'
import { errorText } from '@/lib/errors'
import { formatDateTimeBrussels } from '@/lib/time'
import { useAiUsage, useCheckAiKey, type AiUsage } from './api'
import { aiKeyStateHint, aiKeyStateText, knownAiKeyState, type AiKeyStatus } from './keyState'

const t = uk.aiSettings

/** Settings → "ШІ": month-to-date cost, calls, model, whether the key is set (PRD 5, docs/api.md). */
export function AiUsageSection() {
  const { data, isPending, isError, error, refetch, isFetching } = useAiUsage()

  let body
  if (isPending) {
    body = (
      <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t.loading}
      </div>
    )
  } else if (isError) {
    body = (
      <div role="alert" className="flex flex-col items-start gap-2">
        <p>{t.loadError}</p>
        <p className="text-xs text-muted-foreground">{errorText(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching && <Loader2 className="animate-spin" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  } else {
    body = <UsageDetails usage={data} />
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">{t.title}</h2>
      <div className="rounded-lg border px-4 py-3">{body}</div>
    </section>
  )
}

/**
 * Key state: the health poll (every 15 s, also has checked_at) wins over the usage answer.
 * Neither known (older backend) → null: the old "configured" line is shown instead.
 */
function useKeyStatus(usage: AiUsage): AiKeyStatus | null {
  const health = useHealth()
  // A failed poll may still hold old data: then the usage answer is the fresher source.
  const ai = health.isError ? null : health.data?.ai
  if (ai && knownAiKeyState(ai.state)) return ai
  const usageState = knownAiKeyState(usage.key_state)
  return usageState ? { state: usageState, checked_at: null } : null
}

function KeyHint({ status, configured }: { status: AiKeyStatus | null; configured: boolean }) {
  // With a known state only that state speaks, so "configured" never contradicts it.
  const hint = status
    ? aiKeyStateHint(status.state)
    : configured
      ? null
      : { title: t.notConfigured, text: t.notConfiguredHint }
  if (!hint) return null
  return (
    <p className="text-xs">
      <span className="font-medium">{hint.title}</span>{' '}
      <span className="text-muted-foreground">{hint.text}</span>
    </p>
  )
}

function UsageDetails({ usage }: { usage: AiUsage }) {
  const status = useKeyStatus(usage)
  const keyText = status
    ? aiKeyStateText(status.state)
    : usage.configured
      ? t.configured
      : t.notConfiguredShort
  return (
    <div className="flex flex-col gap-3">
      <KeyHint status={status} configured={usage.configured} />
      <dl className="grid max-w-md grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        <Item label={t.key}>{keyText}</Item>
        {status?.checked_at && (
          <Item label={t.checkedAt}>
            <span className="num">{formatDateTimeBrussels(status.checked_at)}</span>
          </Item>
        )}
        <Item label={t.model}>
          <span className="num">{usage.extraction_model}</span>
        </Item>
        <Item label={t.cost(usage.month)}>
          <span className="num">
            {t.usd}
            {formatDecimal(roundDecimal(usage.cost_usd, 2))}
          </span>
        </Item>
        <Item label={t.calls}>
          <span className="num">{usage.calls}</span>
          {usage.failed_calls > 0 && (
            <span className="ml-2 text-xs text-muted-foreground">{t.failed(usage.failed_calls)}</span>
          )}
        </Item>
      </dl>
      {usage.unpriced_calls > 0 && (
        <p className="text-xs text-muted-foreground">{t.incomplete(usage.unpriced_calls)}</p>
      )}
      {/* An older backend without the key state has no POST /api/ai/check either. */}
      {status && <CheckKeyButton />}
    </div>
  )
}

/** POST /api/ai/check; a failure shows the global error toast (mutation cache). */
function CheckKeyButton() {
  const check = useCheckAiKey()
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="outline" size="sm" onClick={() => check.mutate()} disabled={check.isPending}>
        {check.isPending && <Loader2 className="animate-spin" aria-hidden />}
        {check.isPending ? t.checkingKey : t.checkKey}
      </Button>
      <span className="text-xs text-muted-foreground">{t.restartNote}</span>
    </div>
  )
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </>
  )
}

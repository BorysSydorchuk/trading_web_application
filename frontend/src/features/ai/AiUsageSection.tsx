import type { ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { formatDecimal, roundDecimal } from '@/lib/decimal'
import { errorText } from '@/lib/errors'
import { useAiUsage, type AiUsage } from './api'

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

function UsageDetails({ usage }: { usage: AiUsage }) {
  return (
    <div className="flex flex-col gap-3">
      {!usage.configured && (
        <p className="text-xs">
          <span className="font-medium">{t.notConfigured}</span>{' '}
          <span className="text-muted-foreground">{t.notConfiguredHint}</span>
        </p>
      )}
      <dl className="grid max-w-md grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        <Item label={t.key}>{usage.configured ? t.configured : t.notConfiguredShort}</Item>
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

import { Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { useRegenerateDigest } from './api'
import { BreakdownTables } from './BreakdownTables'
import { DigestCharts } from './charts/DigestCharts'
import { formatPeriod } from './format'
import { MetricBlockCard } from './MetricBlockCard'
import { NextPeriodBias } from './NextPeriodBias'
import { ReviewForm } from './ReviewForm'
import { BiasSummary, RulesTable } from './RulesAndBias'
import type { Digest } from './types'

const p = uk.digests.page

/** The full digest: header, metric blocks, breakdowns, rules, bias, charts, review and next-period bias. */
export function DigestView({ digest }: { digest: Digest }) {
  const snapshot = digest.metrics
  return (
    <div className="flex flex-col gap-6">
      <DigestHeader digest={digest} />
      {digest.ai_summary && (
        <section aria-labelledby="digest-ai" className="flex flex-col gap-1 rounded-lg border p-4">
          <h2 id="digest-ai" className="text-sm font-semibold">{p.aiSummary}</h2>
          <p className="text-sm whitespace-pre-line">{digest.ai_summary}</p>
        </section>
      )}
      <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
        <MetricBlockCard title={uk.digests.blocks.combined} block={snapshot.combined} />
        {snapshot.by_account.map((block) => (
          <MetricBlockCard key={block.account_id} title={block.account_name} block={block} />
        ))}
      </div>
      <DigestCharts snapshot={snapshot} />
      <BreakdownTables breakdowns={snapshot.breakdowns} />
      <div className="grid gap-6 xl:grid-cols-2">
        <RulesTable rules={snapshot.rules} />
        <BiasSummary bias={snapshot.bias} />
      </div>
      <ReviewForm key={digest.id} digest={digest} />
      <NextPeriodBias digest={digest} />
    </div>
  )
}

function DigestHeader({ digest }: { digest: Digest }) {
  const regenerate = useRegenerateDigest()
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="text-lg font-semibold tracking-tight">{formatPeriod(digest.kind, digest.period_start)}</h1>
      <span
        className={cn(
          'rounded-full border px-2 py-0.5 text-xs',
          digest.reviewed ? 'text-muted-foreground' : 'border-primary/50 text-foreground',
        )}
      >
        {digest.reviewed ? p.reviewed : p.notReviewed}
      </span>
      {digest.generated_at && (
        <span className="num text-xs text-muted-foreground">{p.generatedAt(formatDateTimeBrussels(digest.generated_at))}</span>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="ml-auto"
        onClick={() => regenerate.mutate(digest)}
        disabled={regenerate.isPending}
      >
        {regenerate.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />}
        {regenerate.isPending ? p.regenerating : p.regenerate}
      </Button>
    </div>
  )
}

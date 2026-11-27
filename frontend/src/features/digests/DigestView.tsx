import { useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { Pill } from '@/components/studio/Pill'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels } from '@/lib/time'
import { AccountPctLine } from './AccountPctLine'
import { AiSummarySection } from './AiSummarySection'
import { useRegenerateDigest } from './api'
import { BreakdownTables } from './BreakdownTables'
import { DigestCharts } from './charts/DigestCharts'
import { AccountTotalLine, ExcludedTrades } from './ExcludedTrades'
import { ExcursionsCard } from './ExcursionsCard'
import { formatDateBrussels, formatPeriod, missingRPath } from './format'
import { MetricBlockCard } from './MetricBlockCard'
import { NextPeriodBias } from './NextPeriodBias'
import { ReviewForm } from './ReviewForm'
import { BiasSummary, RulesTable } from './RulesAndBias'
import type { Digest } from './types'

const p = uk.digests.page

/** The full digest: header, metric blocks, breakdowns, rules, bias, charts, review and next-period bias. */
export function DigestView({ digest }: { digest: Digest }) {
  const snapshot = digest.metrics
  const [reviewDirty, setReviewDirty] = useState(false)
  return (
    <div className="flex flex-col gap-6">
      <DigestHeader digest={digest} />
      <AiSummarySection digest={digest} />
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        <MetricBlockCard
          title={uk.digests.blocks.combined}
          block={snapshot.combined}
          currency={snapshot.currency}
          missingRHref={missingRPath(digest, snapshot.by_account.map((block) => block.account_id))}
        />
        {snapshot.by_account.map((block) => (
          <MetricBlockCard
            key={block.account_id}
            title={block.account_name}
            block={block}
            currency={snapshot.currency}
            missingRHref={missingRPath(digest, [block.account_id])}
          />
        ))}
      </div>
      <AccountPctLine block={snapshot.account_pct} />
      {snapshot.excluded && <AccountTotalLine block={snapshot.excluded} currency={snapshot.currency} />}
      {snapshot.excluded && <ExcludedTrades block={snapshot.excluded} currency={snapshot.currency} />}
      {snapshot.excursions && <ExcursionsCard block={snapshot.excursions} />}
      <DigestCharts snapshot={snapshot} />
      <BreakdownTables breakdowns={snapshot.breakdowns} currency={snapshot.currency} />
      {/* Rules and bias stacked: the three bias cards need the full width (PM 2026-11-14). */}
      <div className="flex min-w-0 flex-col gap-6">
        <RulesTable rules={snapshot.rules} currency={snapshot.currency} />
        <BiasSummary bias={snapshot.bias} currency={snapshot.currency} />
      </div>
      <ReviewForm key={digest.id} digest={digest} onDirtyChange={setReviewDirty} />
      <NextPeriodBias digest={digest} reviewDirty={reviewDirty} />
    </div>
  )
}

function reviewedText(digest: Digest): string {
  if (!digest.reviewed) return p.notReviewed
  return digest.reviewed_at ? p.reviewedOn(formatDateBrussels(digest.reviewed_at)) : p.reviewed
}

function DigestHeader({ digest }: { digest: Digest }) {
  const regenerate = useRegenerateDigest()
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="type-page-title m-0 text-ink">{formatPeriod(digest.kind, digest.period_start)}</h1>
      {digest.reviewed ? (
        <Pill tone="neutral">{reviewedText(digest)}</Pill>
      ) : (
        <Pill tone="accent" className="border border-lavender-ring">
          {reviewedText(digest)}
        </Pill>
      )}
      {digest.generated_at && (
        <span className="num text-xs text-ink-muted">{p.generatedAt(formatDateTimeBrussels(digest.generated_at))}</span>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="ml-auto"
        onClick={() => regenerate.mutate(digest)}
        disabled={regenerate.isPending}
      >
        {regenerate.isPending ? <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden /> : <RefreshCw aria-hidden />}
        {regenerate.isPending ? p.regenerating : p.regenerate}
      </Button>
    </div>
  )
}

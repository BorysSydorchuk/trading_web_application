import { ArrowLeft, Loader2 } from 'lucide-react'
import { Link, useParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { DescribeEditor } from '@/features/describe/DescribeEditor'
import { InitialSlForm } from '@/features/inbox/InitialSlForm'
import { TradeSummary } from '@/features/describe/TradeSummary'
import { useJournalFields, useTrade } from '@/features/trades/api'
import type { JournalField, TradeDetail } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'

const p = uk.describe.page

function parseTradeId(raw: string | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null
  const id = Number(raw)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

/** /trades/:id/describe — Describe a trade (PRD 6.5). */
export function DescribePage() {
  const tradeId = parseTradeId(useParams().id)
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="sm" className="h-7 text-xs">
          <Link to="/inbox">
            <ArrowLeft aria-hidden />
            {p.back}
          </Link>
        </Button>
        <h1 className="text-lg font-semibold tracking-tight">{p.title}</h1>
      </div>
      {tradeId === null ? <Notice text={uk.errors.not_found} /> : <DescribeContent tradeId={tradeId} />}
    </section>
  )
}

function DescribeContent({ tradeId }: { tradeId: number }) {
  const trade = useTrade(tradeId)
  const fields = useJournalFields()

  if (trade.isPending || fields.isPending) {
    return (
      <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {p.loading}
      </div>
    )
  }
  if (trade.isError) {
    return <LoadError text={p.loadError} error={trade.error} onRetry={() => void trade.refetch()} busy={trade.isFetching} />
  }
  if (fields.isError) {
    return (
      <LoadError text={p.fieldsError} error={fields.error} onRetry={() => void fields.refetch()} busy={fields.isFetching} />
    )
  }
  return <DescribeGate trade={trade.data} fields={fields.data.fields} />
}

function DescribeGate({ trade, fields }: { trade: TradeDetail; fields: readonly JournalField[] }) {
  if (trade.status === 'open') return <Notice text={p.open} />
  if (trade.status === 'needs_sl') {
    return (
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(260px,340px)_minmax(0,1fr)]">
        <TradeSummary trade={trade} />
        <div className="flex flex-col items-start gap-3 rounded-lg border p-4">
          <h2 className="text-sm font-semibold">{uk.inboxPage.groups.needs_sl}</h2>
          <p className="text-xs text-muted-foreground">{p.needsSl}</p>
          <InitialSlForm trade={trade} />
        </div>
      </div>
    )
  }
  // Keyed by trade: the form state starts from this trade's saved journal.
  return <DescribeEditor key={trade.id} trade={trade} fields={fields} />
}

function Notice({ text }: { text: string }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center">
      <p className="text-muted-foreground">{text}</p>
    </div>
  )
}

function LoadError({ text, error, onRetry, busy }: { text: string; error: unknown; onRetry: () => void; busy: boolean }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
      <p>{text}</p>
      <p className="text-xs text-muted-foreground">{errorText(error)}</p>
      <Button variant="outline" size="sm" onClick={onRetry} disabled={busy}>
        {busy && <Loader2 className="animate-spin" aria-hidden />}
        {uk.common.retry}
      </Button>
    </div>
  )
}

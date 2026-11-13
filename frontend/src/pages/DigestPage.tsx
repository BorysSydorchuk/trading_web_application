import { ArrowLeft } from 'lucide-react'
import { Link, Navigate, useParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { usePeriodDigest } from '@/features/digests/api'
import { DigestView } from '@/features/digests/DigestView'
import { digestPagePath, periodStartOf } from '@/features/digests/format'
import { LoadErrorNote, LoadingNote } from '@/features/digests/StateViews'
import { isDigestKind, type DigestKind } from '@/features/digests/types'
import { uk } from '@/i18n/uk'
import { isIsoDate } from '@/lib/time'

const p = uk.digests.page

/** /digests/:kind/:date — one period's digest; a date inside the period moves to its start. */
export function DigestPage() {
  const { kind, date } = useParams()
  const valid = isDigestKind(kind) && date !== undefined && isIsoDate(date)
  return (
    <section className="flex flex-col gap-4">
      <Button asChild variant="ghost" size="sm" className="h-7 self-start text-xs">
        <Link to={`/digests?kind=${valid ? kind : 'weekly'}`}>
          <ArrowLeft aria-hidden />
          {p.back}
        </Link>
      </Button>
      {valid ? (
        <PeriodContent kind={kind} date={date} />
      ) : (
        <p className="rounded-lg border border-dashed px-6 py-8 text-center text-muted-foreground">{p.invalid}</p>
      )}
    </section>
  )
}

function PeriodContent({ kind, date }: { kind: DigestKind; date: string }) {
  const start = periodStartOf(kind, date)
  if (start !== date) return <Navigate replace to={digestPagePath(kind, start)} />
  return <DigestContent kind={kind} start={start} />
}

function DigestContent({ kind, start }: { kind: DigestKind; start: string }) {
  const digest = usePeriodDigest(kind, start)
  if (digest.data === undefined) {
    if (digest.isPending) return <LoadingNote text={p.loading} />
    return (
      <LoadErrorNote text={p.loadError} error={digest.error} onRetry={() => void digest.refetch()} busy={digest.isFetching} />
    )
  }
  return <DigestView digest={digest.data} />
}

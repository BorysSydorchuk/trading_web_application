import { Navigate, useSearchParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { DigestSuggestionCard } from '@/features/dashboard/DigestSuggestionCard'
import { DigestList } from '@/features/digests/DigestList'
import { digestPagePath, periodStartOf } from '@/features/digests/format'
import { DIGEST_KINDS, isDigestKind } from '@/features/digests/types'
import { uk } from '@/i18n/uk'
import { isIsoDate } from '@/lib/time'

/**
 * «Дайджести»: weekly / monthly tabs (`?kind=`). `/digests?kind=&date=` (the Home suggestion
 * link) opens that period's digest page.
 */
export function DigestsPage() {
  const [params, setParams] = useSearchParams()
  const rawKind = params.get('kind')
  const kind = isDigestKind(rawKind) ? rawKind : 'weekly'
  const date = params.get('date')
  if (date !== null && isIsoDate(date) && isDigestKind(rawKind)) {
    return <Navigate replace to={digestPagePath(kind, periodStartOf(kind, date))} />
  }
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold tracking-tight">{uk.pages.digests.title}</h1>
      <DigestSuggestionCard />
      <div role="group" aria-label={uk.digests.kindsLabel} className="flex gap-1">
        {DIGEST_KINDS.map((option) => (
          <Button
            key={option}
            type="button"
            size="sm"
            variant={option === kind ? 'secondary' : 'ghost'}
            aria-pressed={option === kind}
            onClick={() => setParams({ kind: option }, { replace: true })}
          >
            {uk.digests.kinds[option]}
          </Button>
        ))}
      </div>
      <DigestList key={kind} kind={kind} />
    </section>
  )
}

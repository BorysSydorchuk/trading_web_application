import { Navigate, useSearchParams } from 'react-router'
import { selectedToggleClass } from '@/components/studio/tones'
import { DigestSuggestionCard } from '@/features/dashboard/DigestSuggestionCard'
import { DigestList } from '@/features/digests/DigestList'
import { digestPagePath, periodStartOf } from '@/features/digests/format'
import { DIGEST_KINDS, isDigestKind } from '@/features/digests/types'
import { uk } from '@/i18n/uk'
import { isIsoDate } from '@/lib/time'
import { cn } from '@/lib/utils'

const KIND_BUTTON =
  'h-8 rounded-full border px-4 text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring motion-reduce:transition-none'

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
    <section className="flex flex-col gap-5">
      <h1 className="type-page-title m-0 text-ink">{uk.pages.digests.title}</h1>
      <DigestSuggestionCard />
      <div role="group" aria-label={uk.digests.kindsLabel} className="flex gap-1.5">
        {DIGEST_KINDS.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={option === kind}
            onClick={() => setParams({ kind: option }, { replace: true })}
            className={cn(KIND_BUTTON, option === kind ? selectedToggleClass : 'border-input bg-surface text-ink hover:bg-accent')}
          >
            {uk.digests.kinds[option]}
          </button>
        ))}
      </div>
      <DigestList key={kind} kind={kind} />
    </section>
  )
}

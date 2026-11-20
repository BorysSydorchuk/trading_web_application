import { Loader2, Plus } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { useBiasNotes } from '@/features/bias/api'
import { BiasNoteList } from '@/features/bias/BiasNoteList'
import { BIAS_KINDS, isBiasKind, type BiasKind } from '@/features/bias/types'
import { selectedToggleClass } from '@/components/studio/tones'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'

const l = uk.bias.list

/** /bias — bias notes of the last 30 days (PRD 6.6). Kind filter lives in the URL (`?kind=…`). */
export function BiasPage() {
  const [params, setParams] = useSearchParams()
  const kinds = BIAS_KINDS.filter((kind) => params.getAll('kind').includes(kind))
  const notes = useBiasNotes(kinds)

  function setKinds(next: readonly BiasKind[]) {
    setParams(next.map((kind): [string, string] => ['kind', kind]), { replace: true })
  }

  function toggle(kind: BiasKind) {
    setKinds(kinds.includes(kind) ? kinds.filter((k) => k !== kind) : [...kinds, kind])
  }

  const newHref = kinds.length === 1 && isBiasKind(kinds[0]) ? `/bias/new?kind=${kinds[0]}` : '/bias/new'
  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="type-page-title m-0 text-ink">{uk.pages.bias.title}</h1>
        <span className="text-[13px] text-ink-muted">{l.range}</span>
        <Button asChild size="sm" className="ml-auto">
          <Link to={newHref}>
            <Plus aria-hidden />
            {l.newBias}
          </Link>
        </Button>
      </div>
      <KindFilter kinds={kinds} onToggle={toggle} onAll={() => setKinds([])} />
      <ListBody query={notes} filtered={kinds.length > 0} />
    </section>
  )
}

interface KindFilterProps {
  kinds: readonly BiasKind[]
  onToggle: (kind: BiasKind) => void
  onAll: () => void
}

const FILTER_BUTTON =
  'h-8 rounded-full border px-3.5 text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring motion-reduce:transition-none'

function filterClass(active: boolean) {
  return cn(FILTER_BUTTON, active ? selectedToggleClass : 'border-input bg-surface text-ink hover:bg-accent')
}

function KindFilter({ kinds, onToggle, onAll }: KindFilterProps) {
  return (
    <div role="group" aria-label={l.filterLabel} className="flex flex-wrap gap-1.5">
      <button type="button" aria-pressed={kinds.length === 0} onClick={onAll} className={filterClass(kinds.length === 0)}>
        {l.allKinds}
      </button>
      {BIAS_KINDS.map((kind) => (
        <button
          key={kind}
          type="button"
          aria-pressed={kinds.includes(kind)}
          onClick={() => onToggle(kind)}
          className={filterClass(kinds.includes(kind))}
        >
          {uk.bias.kinds[kind]}
        </button>
      ))}
    </div>
  )
}

function ListBody({ query, filtered }: { query: ReturnType<typeof useBiasNotes>; filtered: boolean }) {
  if (query.isPending) {
    return (
      <p role="status" className="flex items-center gap-2 text-xs text-ink-muted">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        {l.loading}
      </p>
    )
  }
  if (query.data === undefined) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-card border border-dashed border-input bg-surface px-6 py-8 text-center">
        <p>{l.loadError}</p>
        <p className="text-xs text-ink-muted">{errorText(query.error)}</p>
        <Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>
          {query.isFetching && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  }
  if (query.data.items.length === 0) {
    return (
      <div className="flex min-h-32 items-center justify-center rounded-card border border-dashed border-input bg-surface px-6 py-8 text-center">
        <p className="text-ink-muted">{filtered ? l.emptyFiltered : l.empty}</p>
      </div>
    )
  }
  return <BiasNoteList notes={query.data.items} />
}

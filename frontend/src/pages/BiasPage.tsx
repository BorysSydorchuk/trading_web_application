import { Loader2, Plus } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { useBiasNotes } from '@/features/bias/api'
import { BiasNoteList } from '@/features/bias/BiasNoteList'
import { BIAS_KINDS, isBiasKind, type BiasKind } from '@/features/bias/types'
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
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold tracking-tight">{uk.pages.bias.title}</h1>
        <span className="text-xs text-muted-foreground">{l.range}</span>
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
  'h-7 rounded-md border px-2.5 text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'

function filterClass(active: boolean) {
  return cn(FILTER_BUTTON, active ? 'border-primary/60 bg-primary text-primary-foreground' : 'border-input hover:bg-accent dark:bg-input/30')
}

function KindFilter({ kinds, onToggle, onAll }: KindFilterProps) {
  return (
    <div role="group" aria-label={l.filterLabel} className="flex flex-wrap gap-1">
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
      <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {l.loading}
      </p>
    )
  }
  if (query.data === undefined) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
        <p>{l.loadError}</p>
        <p className="text-xs text-muted-foreground">{errorText(query.error)}</p>
        <Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>
          {query.isFetching && <Loader2 className="animate-spin" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  }
  if (query.data.items.length === 0) {
    return (
      <div className="flex min-h-32 items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center">
        <p className="text-muted-foreground">{filtered ? l.emptyFiltered : l.empty}</p>
      </div>
    )
  }
  return <BiasNoteList notes={query.data.items} />
}

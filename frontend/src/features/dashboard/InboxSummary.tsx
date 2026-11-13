import { Link } from 'react-router'
import type { InboxCounts } from '@/features/inbox/api'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

const i = uk.dashboard.inbox

/** Needs SL → the inbox (the SL form is there); needs description / drafts → the journal filtered by status. */
const LINKS: ReadonlyArray<{ key: keyof InboxCounts; to: string }> = [
  { key: 'needs_sl', to: '/inbox' },
  { key: 'needs_description', to: '/journal?status=needs_description' },
  { key: 'draft', to: '/journal?status=draft' },
]

export function InboxSummary({ counts }: { counts: InboxCounts }) {
  return (
    <section aria-labelledby="dashboard-inbox" className="flex flex-col gap-2 rounded-lg border p-4">
      <h2 id="dashboard-inbox" className="text-sm font-semibold">{i.title}</h2>
      <ul className="flex flex-col gap-1 text-sm">
        {LINKS.map(({ key, to }) => (
          <li key={key}>
            <Link
              to={to}
              aria-label={`${i[key]}: ${counts[key]}`}
              className="flex items-center justify-between gap-3 rounded px-1 py-0.5 hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              <span>{i[key]}</span>
              <span className={cn('num', counts[key] > 0 ? 'font-semibold' : 'text-muted-foreground')}>{counts[key]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

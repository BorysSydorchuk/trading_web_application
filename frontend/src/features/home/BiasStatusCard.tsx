import { Link } from 'react-router'
import { Card } from '@/components/studio/Card'
import { Button } from '@/components/ui/button'
import { useBiasStatus } from '@/features/bias/api'
import { BIAS_KINDS } from '@/features/bias/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'

const t = uk.bias.status

/** Compact bias status (M4): four periods with «Записати / Відкрити біас» and the server's reminders. */
export function BiasStatusCard() {
  const query = useBiasStatus()
  const status = query.data
  return (
    <Card aria-labelledby="home-bias-status" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="home-bias-status" className="type-card-title text-base">
          {t.title}
        </h2>
        {status && !query.isError && <p className="text-xs text-ink-muted">{t.date(status.date)}</p>}
      </div>
      {query.isPending && <p role="status" className="text-sm text-ink-muted">{t.loading}</p>}
      {query.isError && (
        <div role="alert" className="flex flex-col items-start gap-2">
          <p className="text-destructive">{t.loadError}</p>
          <p className="text-xs text-ink-muted">{errorText(query.error)}</p>
          <Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => void query.refetch()}>
            {uk.common.retry}
          </Button>
        </div>
      )}
      {status && !query.isError && (
        <div className="grid grid-cols-4 gap-3">
          {BIAS_KINDS.map((kind) => {
            const session = kind === 'pre_london' || kind === 'pre_ny' ? status.sessions[kind] : null
            const entry = session ?? (kind === 'weekly' ? status.weekly : status.monthly)
            const remind = session?.remind ?? false
            const href = entry.note_id !== null ? `/bias/${entry.note_id}` : `/bias/new?kind=${kind}&date=${status.date}`
            return (
              <article
                key={kind}
                aria-label={uk.bias.kinds[kind]}
                className={cn(
                  'flex flex-col items-start gap-1.5 rounded-tile border px-3 py-2.5',
                  remind ? 'border-warning-border bg-warning-soft' : 'border-line bg-surface',
                )}
              >
                <h3 className="text-[13px] font-semibold">{uk.bias.kinds[kind]}</h3>
                <p className={cn('text-xs', remind ? 'text-warning' : 'text-ink-muted')}>{entry.note_id === null ? t.missing : t.present}</p>
                {remind && <p role="status" className="text-xs font-semibold text-warning">{t.reminder(uk.bias.kinds[kind])}</p>}
                <Link to={href} className="text-xs font-semibold text-lavender underline-offset-2 outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring">
                  {entry.note_id === null ? t.record : t.open}
                </Link>
              </article>
            )
          })}
        </div>
      )}
    </Card>
  )
}

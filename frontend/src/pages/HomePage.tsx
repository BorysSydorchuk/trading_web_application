import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { useBiasStatus } from '@/features/bias/api'
import { BIAS_KINDS } from '@/features/bias/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'

const t = uk.bias.status

export function HomePage() {
  const query = useBiasStatus()
  const status = query.data
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold tracking-tight">{uk.pages.home.title}</h1>
      <h2 className="text-sm font-semibold">{t.title}</h2>
      {query.isPending && <p role="status" className="text-sm text-muted-foreground">{t.loading}</p>}
      {query.isError && (
        <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border p-4">
          <p>{t.loadError}</p>
          <p className="text-xs text-muted-foreground">{errorText(query.error)}</p>
          <Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => void query.refetch()}>{uk.common.retry}</Button>
        </div>
      )}
      {status && !query.isError && (
        <>
          <p className="text-xs text-muted-foreground">{t.date(status.date)}</p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {BIAS_KINDS.map((kind) => {
              const entry = kind === 'pre_london' || kind === 'pre_ny' ? status.sessions[kind] : status[kind]
              const remind = (kind === 'pre_london' || kind === 'pre_ny') && status.sessions[kind].remind
              const href = entry.note_id !== null ? `/bias/${entry.note_id}` : `/bias/new?kind=${kind}&date=${status.date}`
              return (
                <article key={kind} aria-label={uk.bias.kinds[kind]} className="flex flex-col items-start gap-3 rounded-lg border p-4">
                  <h3 className="text-sm font-semibold">{uk.bias.kinds[kind]}</h3>
                  <p className="text-xs text-muted-foreground">{entry.note_id === null ? t.missing : t.present}</p>
                  {remind && <p role="status" className="text-sm font-medium">{t.reminder(uk.bias.kinds[kind])}</p>}
                  <Button asChild size="sm" variant="outline"><Link to={href}>{entry.note_id === null ? t.record : t.open}</Link></Button>
                </article>
              )
            })}
          </div>
        </>
      )}
    </section>
  )
}

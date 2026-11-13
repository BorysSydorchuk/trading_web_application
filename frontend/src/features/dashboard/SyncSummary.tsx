import { useSyncStatus } from '@/features/sync/api'
import { SyncChips } from '@/features/sync/SyncChips'
import { uk } from '@/i18n/uk'

const s = uk.dashboard.sync

/** Per-account sync status: the status bar chips (last sync time, errors with details on click). */
export function SyncSummary() {
  const { data, isPending, isError } = useSyncStatus()
  return (
    <section aria-labelledby="dashboard-sync" className="flex flex-col gap-2 rounded-lg border p-4 text-xs">
      <h2 id="dashboard-sync" className="text-sm font-semibold">{s.title}</h2>
      {isPending && <p role="status" className="text-muted-foreground">{s.loading}</p>}
      {data?.items.length === 0 && <p className="text-muted-foreground">{s.empty}</p>}
      {/* SyncChips renders the rows, and its own "could not load" chip when the request fails. */}
      {(data !== undefined || isError) && <SyncChips />}
    </section>
  )
}

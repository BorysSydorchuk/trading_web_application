import type { ReactNode } from 'react'
import { isApiError } from '@/api/client'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels, formatRecentBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { knownSyncState, useSyncStatus, type SyncState, type SyncStatusRow } from './api'
import { syncErrorText } from './errors'

const s = uk.sync

// Status dots, not P&L: kept small and muted except for problems.
const dotClass: Record<SyncState, string> = {
  ok: 'bg-profit/70',
  warning: 'bg-amber-400',
  running: 'bg-muted-foreground animate-pulse',
  never: 'bg-muted-foreground/40',
  stale: 'bg-amber-400',
  error: 'bg-loss',
}

const textClass: Record<SyncState, string> = {
  ok: 'text-muted-foreground',
  warning: 'text-amber-400',
  running: 'text-muted-foreground',
  never: 'text-muted-foreground',
  stale: 'text-amber-400',
  error: 'text-loss',
}

/** Unknown (future) states: neutral grey. */
const NEUTRAL_DOT = 'bg-muted-foreground/60'
const NEUTRAL_TEXT = 'text-muted-foreground'

function minutesSince(isoUtc: string, nowMs: number): number | null {
  const then = Date.parse(isoUtc)
  return Number.isNaN(then) ? null : Math.max(0, Math.floor((nowMs - then) / 60_000))
}

function syncedText(row: SyncStatusRow): string | null {
  return row.last_success_utc ? `${s.syncedAt} ${formatRecentBrussels(row.last_success_utc)}` : null
}

function shortText(row: SyncStatusRow, nowMs: number): string {
  const state = knownSyncState(row.state)
  switch (state) {
    case 'ok':
      return syncedText(row) ?? s.states.ok
    case 'warning': {
      const synced = syncedText(row)
      return synced ? `${synced} · ${s.attention}` : s.states.warning
    }
    case 'running':
      return s.running
    case 'never':
      return s.never
    case 'stale': {
      // "stale" = the latest attempt is too old (docs/api.md), whatever its outcome.
      const since = row.last_attempt_utc ?? row.last_success_utc
      const minutes = since ? minutesSince(since, nowMs) : null
      return minutes === null ? s.staleNoSuccess : s.staleMinutes(minutes)
    }
    case 'error':
      return syncErrorText(row.error_code)
    case null:
      return row.state
  }
}

function stateLabel(state: string): string {
  const known = knownSyncState(state)
  return known ? s.states[known] : state
}

/**
 * Per-account sync chips for the status bar. A failed poll keeps the last known data on screen.
 * Hidden only when the endpoint does not exist yet (404) and nothing was ever loaded.
 */
export function SyncChips() {
  const { data, error, dataUpdatedAt } = useSyncStatus()
  if (!data) {
    if (!error || (isApiError(error) && error.code === 'not_found')) return null
    return (
      <span aria-live="off" className="flex shrink-0 items-center gap-1.5 px-1.5">
        <span className="size-2 shrink-0 rounded-full bg-muted-foreground/40" aria-hidden />
        {s.loadError}
      </span>
    )
  }
  if (data.items.length === 0) return null

  return (
    <ul aria-label={s.label} aria-live="off" className="flex min-w-0 items-center gap-1 overflow-x-auto">
      {data.items.map((row) => (
        <li key={row.account_id} className="shrink-0">
          <SyncChip row={row} nowMs={dataUpdatedAt} />
        </li>
      ))}
    </ul>
  )
}

function SyncChip({ row, nowMs }: { row: SyncStatusRow; nowMs: number }) {
  const text = shortText(row, nowMs)
  const state = knownSyncState(row.state)
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'flex items-center gap-1.5 rounded border border-transparent px-1.5 py-0.5 hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none',
            state === 'error' && 'border-loss/40',
            state === 'warning' && 'border-amber-400/40',
          )}
          aria-label={`${row.account_name}: ${text}`}
        >
          <span className={cn('size-2 shrink-0 rounded-full', state ? dotClass[state] : NEUTRAL_DOT)} aria-hidden />
          <span className="max-w-32 truncate text-sidebar-foreground">{row.account_name}</span>
          <span className={cn('whitespace-nowrap tabular-nums', state ? textClass[state] : NEUTRAL_TEXT)}>
            {text}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-80 text-xs">
        <SyncDetails row={row} />
      </PopoverContent>
    </Popover>
  )
}

function SyncDetails({ row }: { row: SyncStatusRow }) {
  const d = s.details
  const state = knownSyncState(row.state)
  // Warning (sync worked, something needs attention) is amber; any error kept on the row is red.
  const isWarning = state === 'warning' || row.error_code === 'positions_skipped'
  const hasProblem = row.error_code !== null || row.error_message !== null
  const problemText =
    row.error_code === null && isWarning ? s.states.warning : syncErrorText(row.error_code)
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm font-medium">{row.account_name}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <DetailRow label={d.state}>
          <span className={state ? textClass[state] : NEUTRAL_TEXT}>{stateLabel(row.state)}</span>
        </DetailRow>
        <DetailRow label={d.lastAttempt}>
          <TimeValue value={row.last_attempt_utc} />
        </DetailRow>
        <DetailRow label={d.lastSuccess}>
          <TimeValue value={row.last_success_utc} />
        </DetailRow>
        <DetailRow label={d.serverOffset}>
          {row.server_offset_hours === null ? (
            uk.common.empty
          ) : (
            <span className="num">{s.utcOffset(row.server_offset_hours)}</span>
          )}
        </DetailRow>
        <DetailRow label={d.openPositions}>
          <span className="num">{row.open_positions ?? uk.common.empty}</span>
        </DetailRow>
      </dl>
      {hasProblem && (
        <div
          className={cn(
            'flex flex-col gap-0.5 rounded border px-2 py-1.5',
            isWarning ? 'border-amber-400/40' : 'border-loss/40',
          )}
        >
          <p className={isWarning ? 'text-amber-400' : 'text-loss'}>
            {isWarning ? d.warning : d.error}
            {': '}
            {problemText}
          </p>
          {row.error_message && (
            <p className="break-words text-muted-foreground">{row.error_message}</p>
          )}
        </div>
      )}
      <p className="text-muted-foreground">{d.timeZoneNote}</p>
    </div>
  )
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </>
  )
}

function TimeValue({ value }: { value: string | null }) {
  if (value === null) return <>{uk.common.empty}</>
  return <span className="num">{formatDateTimeBrussels(value)}</span>
}

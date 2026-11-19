import type { BackupStatus } from '@/api/health'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels } from '@/lib/time'

function message(code: string) {
  return Object.hasOwn(uk.backups.errors, code)
    ? uk.backups.errors[code as keyof typeof uk.backups.errors]
    : uk.backups.errors.state_unavailable
}

export function BackupChip({ status }: { status?: BackupStatus | null }) {
  if (!status) return null
  const t = uk.backups
  const label = status.state === 'running' ? t.running
    : status.error_code ? t.failed : status.overdue ? t.overdue : t.ok
  const warning = status.error_code || status.overdue
  const date = (value: string | null) => value ? formatDateTimeBrussels(value) : t.never
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" aria-label={`${t.title}: ${label}`}
          className="flex shrink-0 items-center gap-1.5 rounded border border-sidebar-border px-1.5 py-0.5 hover:bg-sidebar-accent">
          <span className={warning ? 'text-warning' : ''}>{t.title}: {label}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="flex w-96 max-w-[95vw] flex-col gap-2 text-xs">
        <p className="font-medium">{t.title}</p>
        {status.overdue && <p className="text-warning">{t.overdue}</p>}
        {status.error_code && <p>{message(status.error_code)}</p>}
        <dl className="grid grid-cols-2 gap-2">
          <dt>{t.lastSuccess}</dt><dd>{date(status.last_success_at)}</dd>
          <dt>{t.next}</dt><dd>{date(status.next_due_at)}</dd>
          <dt>{t.failures}</dt><dd>{status.failed_attempts}</dd>
          <dt>{t.attempts}</dt><dd>{status.attempts}</dd>
          {status.last_failure_at && <><dt>{t.lastFailure}</dt><dd>{date(status.last_failure_at)}</dd></>}
          {status.retry_at && <><dt>{t.retry}</dt><dd>{date(status.retry_at)}</dd></>}
        </dl>
        {status.last_error_code && status.last_error_code !== status.error_code &&
          <p>{message(status.last_error_code)}</p>}
        <p className="text-muted-foreground">{t.schedule}</p>
      </PopoverContent>
    </Popover>
  )
}

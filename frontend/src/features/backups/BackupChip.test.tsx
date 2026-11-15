import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { BackupChip } from './BackupChip'

const success = {
  state: 'ok', last_success_at: '2026-10-25T17:00:00Z', last_failure_at: null,
  error_code: null, last_error_code: null, overdue: false, attempts: 1, failed_attempts: 0,
  next_due_at: '2026-10-26T17:00:00Z', retry_at: null,
}

describe('Backup status', () => {
  it('shows success and full Brussels dates in accessible details', async () => {
    const { user } = renderWithProviders(<BackupChip status={success} />)
    await user.click(screen.getByRole('button', { name: /Резервні копії/ }))
    const details = within(screen.getByRole('dialog'))
    expect(details.getByText('25.10.2026, 18:00:00')).toBeInTheDocument()
    expect(details.getByText('26.10.2026, 18:00:00')).toBeInTheDocument()
    expect(details.getByText(uk.backups.schedule)).toBeInTheDocument()
  })

  it.each(['backup_failed', 'dependencies_unhealthy', 'interrupted', 'state_unavailable',
    'retention_failed', 'worker_unavailable', 'archive_invalid', 'backup_locked'])('shows actionable Ukrainian error %s', async code => {
    const { user } = renderWithProviders(<BackupChip status={{ ...success, state: 'failed',
      error_code: code, last_error_code: code, overdue: true, failed_attempts: 2,
      last_failure_at: '2026-10-25T17:05:00Z', retry_at: '2026-10-25T17:10:00Z' }} />)
    await user.click(screen.getByRole('button', { name: /Резервні копії/ }))
    const details = within(screen.getByRole('dialog'))
    expect(details.getByText(uk.backups.overdue)).toBeInTheDocument()
    expect(details.getAllByText(uk.backups.errors[code as keyof typeof uk.backups.errors]).length).toBeGreaterThan(0)
    expect(details.getByText('25.10.2026, 18:10:00')).toBeInTheDocument()
  })

  it('does not echo unknown server error strings', async () => {
    const { user } = renderWithProviders(<BackupChip status={{ ...success, state: 'failed', error_code: 'secret' }} />)
    await user.click(screen.getByRole('button', { name: /Резервні копії/ }))
    expect(screen.queryByText('secret')).not.toBeInTheDocument()
    expect(screen.getByText(uk.backups.errors.state_unavailable)).toBeInTheDocument()
  })

  it('preserves the last failure history after recovery', async () => {
    const { user } = renderWithProviders(<BackupChip status={{ ...success, failed_attempts: 1,
      last_error_code: 'backup_failed', last_failure_at: '2026-10-25T16:55:00Z' }} />)
    await user.click(screen.getByRole('button', { name: /Резервні копії/ }))
    expect(screen.getByText(uk.backups.errors.backup_failed)).toBeInTheDocument()
  })

  it('hides absent status from an older backend', () => {
    renderWithProviders(<BackupChip />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

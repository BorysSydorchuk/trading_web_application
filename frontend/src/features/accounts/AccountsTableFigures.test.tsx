import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { account } from '@/features/calculator/calculator.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { AccountsTable } from './AccountsTable'

// PM 2026-11-27: «Головна» is % only, so the exact figures live here.
describe('«Рахунки»: balance and equity in the account currency', () => {
  it('shows both with the currency and the sync time', () => {
    const synced = account({ balance: '98022.17', equity: '98555.92', currency: 'USD', balance_synced_at: '2026-11-27T13:00:00Z' })
    renderWithProviders(<AccountsTable accounts={[synced]} onEdit={vi.fn()} onDelete={vi.fn()} />)
    expect(screen.getByRole('columnheader', { name: uk.accounts.columns.equity })).toBeInTheDocument()
    expect(screen.getByTestId('account-balance')).toHaveTextContent(/98.022\.17 USD/)
    expect(screen.getByTestId('account-equity')).toHaveTextContent(/98.555\.92 USD/)
    expect(screen.getAllByText(uk.accounts.balanceUpdated, { exact: false }).length).toBeGreaterThanOrEqual(2)
  })

  it('an account that never synced says so for both', () => {
    renderWithProviders(<AccountsTable accounts={[account({ balance: null, equity: null, balance_synced_at: null })]} onEdit={vi.fn()} onDelete={vi.fn()} />)
    expect(screen.getAllByText(uk.accounts.balanceNotSynced)).toHaveLength(2)
  })
})

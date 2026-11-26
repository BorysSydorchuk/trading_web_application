import { screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { account } from '@/features/calculator/calculator.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { setupUser } from '@/test/user'
import { AccountFormDialog } from './AccountFormDialog'
import { AccountsTable } from './AccountsTable'
import type { Account, FirmRules } from './types'

const t = uk.accounts.firmRules

function keyFunding(overrides: Partial<FirmRules> = {}): FirmRules {
  return {
    firm: 'KeyFunding', source: 'firm', daily_loss_pct: '4.00', max_loss_pct: '8.00', max_loss_type: 'static',
    profit_target_pct: '8.00', daily_basis: 'balance', daily_reset: '00:00', reset_timezone: 'server',
    to_verify: ['daily_basis', 'daily_reset'], ...overrides,
  }
}

const KF = account({ id: 5, platform: 'ctrader', name: 'KF P1', firm: 'KeyFunding', firm_rules: keyFunding() })

function renderForm(acc: Account = KF) {
  renderWithProviders(<AccountFormDialog open onOpenChange={vi.fn()} account={acc} />)
}

describe('Firm rules note in the account form', () => {
  it('shows the effective KeyFunding rules and one «Перевірити» line per to_verify item', () => {
    renderForm()
    const note = screen.getByTestId('firm-rules-note')
    expect(note).toHaveTextContent('Правила KeyFunding (config/firms.yaml):')
    expect(note).toHaveTextContent(
      'денний збиток 4% від балансу на початок дня, скидання 00:00 за часом сервера; макс. збиток 8% статичний; ціль 8%.',
    )
    const lines = within(note).getAllByTestId('firm-rules-verify').map((el) => el.textContent)
    expect(lines).toEqual([
      'Перевірити: база денного ліміту (баланс на початок дня)',
      'Перевірити: час скидання дня (00:00 за часом сервера)',
    ])
  })

  it('shows no verify lines when nothing is left to verify', () => {
    renderForm(account({ firm_rules: keyFunding({ to_verify: [], reset_timezone: 'Europe/Prague' }) }))
    expect(screen.getByTestId('firm-rules-note')).toHaveTextContent('скидання 00:00 (Europe/Prague)')
    expect(screen.queryByTestId('firm-rules-verify')).not.toBeInTheDocument()
  })

  it('KeyFunding with empty to_verify (confirmed): no «Перевірити» anywhere, form or table', () => {
    const confirmed = account({ id: 7, firm: 'KeyFunding', firm_rules: keyFunding({ to_verify: [] }) })
    renderForm(confirmed)
    expect(screen.getByTestId('firm-rules-note')).not.toHaveTextContent('Перевірити')
    expect(screen.queryByTestId('firm-rules-verify')).not.toBeInTheDocument()
  })

  it('table hint without the verify count when to_verify is empty', () => {
    const confirmed = account({ id: 7, firm: 'KeyFunding', firm_rules: keyFunding({ to_verify: [] }) })
    renderWithProviders(<AccountsTable accounts={[confirmed]} onEdit={vi.fn()} onDelete={vi.fn()} />)
    const hint = screen.getByTestId('firm-rules-hint')
    expect(hint).toHaveTextContent(t.tableHint)
    expect(hint).not.toHaveTextContent(t.tableVerify(0))
    expect(hint.parentElement).not.toHaveAttribute('title', expect.stringContaining('Перевірити'))
  })

  it.each([
    ['account', keyFunding({ source: 'account' })],
    ['fallback', keyFunding({ source: 'fallback' })],
    ['null', null],
    ['absent', undefined],
  ])('keeps the current form without a note (%s)', (_name, rules) => {
    renderForm(account({ firm_rules: rules }))
    expect(screen.getByText(uk.accounts.form.sections.rules)).toBeInTheDocument()
    expect(screen.queryByTestId('firm-rules-note')).not.toBeInTheDocument()
  })
})

describe('Firm rules hint in the accounts table', () => {
  it('marks only accounts with config/firms.yaml rules and counts the items to verify', async () => {
    const user = setupUser()
    const onEdit = vi.fn()
    renderWithProviders(<AccountsTable accounts={[KF, account({ id: 6, name: 'FN' })]} onEdit={onEdit} onDelete={vi.fn()} />)

    expect(screen.getAllByTestId('firm-rules-hint')).toHaveLength(1)
    const hint = screen.getByTestId('firm-rules-hint')
    expect(hint).toHaveTextContent(`${t.tableHint} · ${t.tableVerify(2)}`)
    expect(hint.parentElement).toHaveAttribute('title', expect.stringContaining('Перевірити: час скидання дня'))

    await user.click(screen.getByRole('button', { name: `${uk.accounts.actions.edit}: KF P1` }))
    expect(onEdit).toHaveBeenCalledWith(KF)
  })
})

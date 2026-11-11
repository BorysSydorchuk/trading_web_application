import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { result } from './calculator.fixture'
import { CalculatorResult } from './CalculatorResult'

const r = uk.calculator.result

const withCurrent = result({
  balance: '10000.00',
  risk_budget: '100.00',
  current_balance: '9857.58',
  current_balance_synced_at: '2026-11-10T07:00:00Z',
})

function renderResult(compact: boolean, data = withCurrent) {
  render(<CalculatorResult result={data} brokerSymbol={null} digits={2} margin={null} compact={compact} />)
}

describe('CalculatorResult risk base', () => {
  it('shows the account size next to the budget and the current balance as info on the page', () => {
    renderResult(false)
    expect(screen.getByText(r.riskBase('10 000.00', 'USD'))).toBeInTheDocument()
    expect(screen.getByText(r.currentBalance('9 857.58', 'USD', '10.11.2026, 08:00:00'))).toBeInTheDocument()
  })

  it('shows the current balance without a date when the sync time is unknown', () => {
    renderResult(false, { ...withCurrent, current_balance_synced_at: null })
    expect(screen.getByText(r.currentBalanceNoDate('9 857.58', 'USD'))).toBeInTheDocument()
  })

  it('shows only the account-size line in the compact Home panel', () => {
    renderResult(true)
    expect(screen.getByText(r.riskBase('10 000.00', 'USD'))).toBeInTheDocument()
    expect(screen.queryByText(r.currentBalance('9 857.58', 'USD', '10.11.2026, 08:00:00'))).not.toBeInTheDocument()
  })
})

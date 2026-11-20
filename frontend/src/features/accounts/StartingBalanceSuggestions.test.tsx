import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { account } from '@/features/calculator/calculator.fixture'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { setupUser } from '@/test/user'
import { uk } from '@/i18n/uk'
import { StartingBalanceSuggestions } from './StartingBalanceSuggestions'

const t = uk.accounts.startingSuggestion
const SUGGESTED = { amount: '10000.00', time: '2026-11-10T12:53:29Z' }

describe('StartingBalanceSuggestions', () => {
  it('shows nothing when no account has a suggestion', () => {
    renderWithProviders(<StartingBalanceSuggestions accounts={[account(), account({ id: 2, starting_balance_suggestion: null })]} />)
    expect(screen.queryByTestId('starting-balance-suggestion')).not.toBeInTheDocument()
  })

  it('applies the first MT5 deposit as the starting balance with one click', async () => {
    const user = setupUser()
    let body: unknown = null
    mockApi(
      http.patch('/api/accounts/3', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json(account({ id: 3, starting_balance: '10000.00' }))
      }),
    )
    renderWithProviders(
      <StartingBalanceSuggestions
        accounts={[account({ id: 3, name: 'FN Stellar Funded 2', starting_balance: '9986.05', starting_balance_suggestion: SUGGESTED })]}
      />,
    )

    const row = screen.getByTestId('starting-balance-suggestion')
    expect(row).toHaveTextContent('FN Stellar Funded 2:')
    expect(row).toHaveTextContent('10 000.00 USD')
    expect(row).toHaveTextContent('9 986.05 USD')
    await user.click(screen.getByRole('button', { name: t.apply }))

    expect(body).toEqual({ starting_balance: '10000.00' })
  })

  it('shows a visible error when saving fails', async () => {
    const user = setupUser()
    mockApi(http.patch('/api/accounts/3', () => HttpResponse.json({ error: { code: 'x', message: 'boom' } }, { status: 500 })))
    renderWithProviders(<StartingBalanceSuggestions accounts={[account({ id: 3, starting_balance_suggestion: SUGGESTED })]} />)

    await user.click(screen.getByRole('button', { name: t.apply }))

    expect(await screen.findByRole('alert')).toHaveTextContent(t.error)
  })
})

import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '@/test/render'
import { fixtureBlock } from './digest.fixture'
import { missingRPath } from './format'
import { MetricBlockCard } from './MetricBlockCard'

const HREF = '/journal?period=custom&from=2026-11-09&to=2026-11-15&missing_r=true'

describe('«Сума R» coverage link (PM 2026-11-14)', () => {
  it('links n/N to the trades without R when R covers fewer trades', async () => {
    // fixture: 4 trades, total_r over n = 3
    const { user, router } = renderWithProviders(
      <MetricBlockCard title="Разом" block={fixtureBlock()} currency="USD" missingRHref={HREF} />,
      { routes: [{ path: '/journal', element: <span data-testid="journal" /> }] },
    )

    const link = screen.getByRole('link', { name: 'показати 1 угод без R у журналі' })
    expect(link).toHaveTextContent('за 3/4 угод')

    await user.click(link)
    expect(router.state.location.pathname).toBe('/journal')
    expect(router.state.location.search).toBe('?period=custom&from=2026-11-09&to=2026-11-15&missing_r=true')
  })

  it('shows plain text when every trade has R', () => {
    const block = fixtureBlock()
    const totalR = block.metrics.total_r
    if (!totalR) throw new Error('fixture has total_r')
    const full = { ...block, metrics: { ...block.metrics, total_r: { ...totalR, n: 4 } } }

    renderWithProviders(<MetricBlockCard title="Разом" block={full} currency="USD" missingRHref={HREF} />)

    expect(screen.getByText('(за 4/4 угод)')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /без R/ })).not.toBeInTheDocument()
  })

  it('builds the journal path for the period and one account', () => {
    const digest = { period_start: '2026-11-09', period_end: '2026-11-15' }

    expect(missingRPath(digest)).toBe(HREF)
    expect(missingRPath(digest, 2)).toBe(`${HREF}&account=2`)
  })
})

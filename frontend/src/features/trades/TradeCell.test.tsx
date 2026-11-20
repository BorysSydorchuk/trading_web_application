import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fixtureTrade } from '@/features/describe/trade.fixture'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { TradeCell } from './TradeCell'

const LABELS: Record<string, string> = { outside_session: 'Вхід поза сесією', risk_above_limit: 'Ризик вище ліміту' }
const trade = fixtureTrade({ violations: ['outside_session', 'risk_above_limit'] })

describe('TradeCell violations (M8-10c)', () => {
  it('Journal: one red count pill, names in the hover title and as screen-reader text', () => {
    renderWithProviders(<TradeCell trade={trade} column="violations" violationLabel={(key) => LABELS[key] ?? key} />)

    const pill = screen.getByText('2')
    expect(pill).toHaveAttribute('aria-hidden', 'true')
    expect(pill).toHaveAttribute('title', 'Вхід поза сесією, Ризик вище ліміту')
    expect(screen.getByText('Вхід поза сесією')).toBeInTheDocument()
    expect(screen.getByText('Ризик вище ліміту').closest('.sr-only')).not.toBeNull()
  })

  it('«Потрібен опис» (no violationLabel): visible named badges, no count pill', async () => {
    mockApi(http.get('/api/journal-fields', () => HttpResponse.json({ fields: [] })))
    renderWithProviders(<TradeCell trade={trade} column="violations" />)

    const names = screen.getByTestId('violation-names')
    expect(names.children).toHaveLength(2)
    expect(names.querySelector('.sr-only')).toBeNull()
    expect(screen.queryByText('2')).not.toBeInTheDocument()
  })
})

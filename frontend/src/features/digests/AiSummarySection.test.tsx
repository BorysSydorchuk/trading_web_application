import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { AiSummarySection } from './AiSummarySection'
import { fixtureDigest } from './digest.fixture'

const t = uk.digests.ai

describe('AiSummarySection: stale mark (M8-01b)', () => {
  it('marks a saved summary stale after the numbers were recomputed', () => {
    renderWithProviders(
      <AiSummarySection digest={fixtureDigest({ ai_summary: 'Факт: 3 угоди.', ai_summary_stale_at: '2026-11-12T14:00:00Z' })} />,
    )
    expect(screen.getByRole('status')).toHaveTextContent(t.stale('12.11, 15:00'))
    expect(screen.getByText('Факт: 3 угоди.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: t.refresh })).toBeInTheDocument()
  })

  it('shows no mark for a current summary or when there is no summary', () => {
    const { unmount } = renderWithProviders(<AiSummarySection digest={fixtureDigest({ ai_summary: 'Факт.', ai_summary_stale_at: null })} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    unmount()
    renderWithProviders(<AiSummarySection digest={fixtureDigest({ ai_summary: null, ai_summary_stale_at: '2026-11-12T14:00:00Z' })} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})

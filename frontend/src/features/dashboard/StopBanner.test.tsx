import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { FirmLimitBanner } from './FirmLimitBanner'
import { StopBanner } from './StopBanner'
import type { Dashboard } from './types'

const d = uk.dashboard
const f = d.firmBanner

/** Both banners as HomePage renders them: firm first, then personal. */
function renderBanners(stop: Dashboard['stop']) {
  render(
    <>
      <FirmLimitBanner stop={stop} />
      <StopBanner stop={stop} />
    </>,
  )
}

describe('StopBanner and FirmLimitBanner', () => {
  it('render nothing without any stop (old payload without the firm flags)', () => {
    renderBanners({ today: false, week: false })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('render nothing when the firm flags are false', () => {
    renderBanners({ today: false, week: false, firm_day: false, firm_max_loss: false })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('personal stop only: StopBanner, no firm banner', () => {
    renderBanners({ today: true, week: true, firm_day: false, firm_max_loss: false })
    const banner = screen.getByRole('alert')
    expect(banner).toHaveTextContent(d.stopToday)
    expect(banner).toHaveTextContent(d.stopWeek)
    expect(screen.queryByTestId('firm-limit-banner')).not.toBeInTheDocument()
  })

  it('firm limit only: the critical banner, no personal StopBanner', () => {
    renderBanners({ today: false, week: false, firm_day: true, firm_max_loss: false })
    const banner = screen.getByRole('alert')
    expect(banner).toHaveAttribute('data-testid', 'firm-limit-banner')
    expect(banner).toHaveClass('bg-loss')
    expect(banner).toHaveTextContent(f.day)
    expect(banner).not.toHaveTextContent(f.maxLoss)
    expect(banner).toHaveTextContent(f.hint)
    expect(banner).not.toHaveTextContent(d.stopHint)
  })

  it('both: two separate banners, firm first, StopBanner without firm lines', () => {
    renderBanners({ today: true, week: false, firm_day: true, firm_max_loss: true })
    const [firm, personal] = screen.getAllByRole('alert')
    if (!firm || !personal) throw new Error('two banners expected')
    expect(firm).toHaveAttribute('data-testid', 'firm-limit-banner')
    expect(within(firm).getByText(f.day)).toBeInTheDocument()
    expect(within(firm).getByText(f.maxLoss)).toBeInTheDocument()
    expect(personal).toHaveTextContent(d.stopToday)
    expect(personal).not.toHaveTextContent(f.day)
    expect(personal).not.toHaveTextContent(f.maxLoss)
  })

  it('StopBanner alone ignores the firm flags', () => {
    render(<StopBanner stop={{ today: false, week: false, firm_day: true, firm_max_loss: true }} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { StopBanner } from './StopBanner'

const d = uk.dashboard

describe('StopBanner firm limits', () => {
  it('renders nothing without any stop (old payload without the firm flags)', () => {
    render(<StopBanner stop={{ today: false, week: false }} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders nothing when both firm flags are false', () => {
    render(<StopBanner stop={{ today: false, week: false, firm_day: false, firm_max_loss: false }} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows the banner for the firm daily limit alone', () => {
    render(<StopBanner stop={{ today: false, week: false, firm_day: true, firm_max_loss: false }} />)
    const banner = screen.getByRole('alert')
    expect(banner).toHaveTextContent(d.stopFirmDay)
    expect(banner).not.toHaveTextContent(d.stopFirmMaxLoss)
    expect(banner).toHaveTextContent(d.stopHint)
  })

  it('shows the firm max loss line next to the personal stops', () => {
    render(<StopBanner stop={{ today: true, week: false, firm_day: false, firm_max_loss: true }} />)
    const banner = screen.getByRole('alert')
    expect(banner).toHaveTextContent(d.stopToday)
    expect(banner).toHaveTextContent(d.stopFirmMaxLoss)
    expect(banner).not.toHaveTextContent(d.stopFirmDay)
  })
})

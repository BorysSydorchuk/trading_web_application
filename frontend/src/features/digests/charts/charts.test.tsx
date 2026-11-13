import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { EquityChart } from './EquityChart'
import { HourHeatmap } from './HourHeatmap'
import { RDistributionChart } from './RDistributionChart'

const c = uk.digests.charts
const [, , , , , SATURDAY = '', SUNDAY = ''] = uk.trades.weekdays

describe('digest SVG charts', () => {
  it('draws the equity line from 0 through every point', () => {
    render(<EquityChart title="Крива" points={[{ time: '2026-11-10T10:00:00Z', cum_pnl: '100.00' }, { time: '2026-11-10T12:00:00Z', cum_pnl: '-50.00' }]} />)
    expect(screen.getByRole('img', { name: 'Крива' })).toBeInTheDocument()
    expect(screen.getByTestId('equity-line').getAttribute('points')?.split(' ')).toHaveLength(3)
    expect(screen.getByText(c.equityEnd('−50.00'))).toBeInTheDocument()
  })

  it('labels the R edge buckets «≤ −2.5» and «≥ 3»', () => {
    const { container } = render(
      <RDistributionChart
        buckets={[
          { lower: '-3.0000', upper: '-2.5000', count: 1 },
          { lower: '0.5000', upper: '1.0000', count: 4 },
          { lower: '3.0000', upper: '3.5000', count: 2 },
        ]}
      />,
    )
    expect(screen.getByText('≤ −2.5')).toBeInTheDocument()
    expect(screen.getByText('≥ 3')).toBeInTheDocument()
    expect(screen.getByText('0.50…1.00')).toBeInTheDocument()
    expect(container.querySelectorAll('rect')).toHaveLength(3)
  })

  it('draws heatmap cells with a weekend row only when present', () => {
    const { container } = render(
      <HourHeatmap cells={[{ weekday: 0, hour: 9, trades: 2, net_pnl: '100.00' }, { weekday: 5, hour: 11, trades: 1, net_pnl: '-20.00' }]} />,
    )
    expect(container.querySelectorAll('[data-cell]')).toHaveLength(2)
    expect(screen.getByText(SATURDAY)).toBeInTheDocument()
    expect(screen.queryByText(SUNDAY)).not.toBeInTheDocument()
    expect(container.querySelector('[data-cell="0-9"] rect')).toHaveClass('fill-profit')
    expect(container.querySelector('[data-cell="5-11"] rect')).toHaveClass('fill-loss')
  })

  it('shows an empty note without data', () => {
    render(<RDistributionChart buckets={[]} />)
    expect(screen.getByText(c.empty)).toBeInTheDocument()
  })
})

import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { setupUser } from '@/test/user'
import { KpiCard } from './KpiCard'

function Harness() {
  const [on, setOn] = useState(false)
  return <KpiCard label="Win rate" value="57.0%" hint={on ? 'на графіку' : 'графік'} tone="accent" selected={on} onClick={() => setOn(!on)} />
}

describe('KpiCard', () => {
  it('is a toggle button that flips aria-pressed and shows the selected ring', async () => {
    const user = setupUser()
    render(<Harness />)
    const card = screen.getByRole('button', { name: /Win rate/ })
    expect(card).toHaveAttribute('aria-pressed', 'false')
    expect(card).toHaveClass('border', 'border-line')
    await user.click(card)
    expect(card).toHaveAttribute('aria-pressed', 'true')
    expect(card).toHaveClass('border-2', 'border-lavender-ring')
    expect(screen.getByText('на графіку')).toHaveClass('bg-lavender-soft', 'text-lavender')
    await user.click(card)
    expect(card).toHaveAttribute('aria-pressed', 'false')
  })

  it.each([
    ['profit', 'text-profit', 'border-profit-mid', 'from-profit-wash'],
    ['loss', 'text-loss', 'border-loss-mid', 'from-peach-soft'],
    ['accent', 'text-lavender', 'border-lavender-ring', 'from-lavender-soft'],
  ] as const)('%s tone colours the value, ring and wash', (tone, valueClass, ringClass, washClass) => {
    render(<KpiCard label="KPI" value="+212" tone={tone} selected />)
    expect(screen.getByRole('button', { name: /KPI/ })).toHaveClass(ringClass, washClass)
    expect(screen.getByText('+212')).toHaveClass('type-kpi', valueClass)
  })

  it('renders the sparkline slot and lifts on hover (lift utility, off under reduced motion)', () => {
    render(<KpiCard label="KPI" value="1" sparkline={<svg data-testid="spark" aria-hidden />} />)
    expect(screen.getByTestId('spark')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /KPI/ })).toHaveClass('lift')
  })
})

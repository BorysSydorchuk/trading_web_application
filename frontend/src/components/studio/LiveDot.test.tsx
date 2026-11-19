import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LiveDot } from './LiveDot'

describe('LiveDot', () => {
  it('is decorative without a label', () => {
    const { container } = render(<LiveDot />)
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('is a named image with a label', () => {
    render(<LiveDot label="наживо" />)
    expect(screen.getByRole('img', { name: 'наживо' })).toBeInTheDocument()
  })

  it('pulses through the live-pulse utility (switched off under prefers-reduced-motion in CSS)', () => {
    const { container } = render(<LiveDot />)
    expect(container.firstElementChild).toHaveClass('live-pulse', 'bg-profit-strong', 'rounded-full')
  })
})

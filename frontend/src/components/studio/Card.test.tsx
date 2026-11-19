import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'
import { Tile } from './Tile'

const BODY = 'x'

describe('Card', () => {
  it('renders a section region with the card radius and surface', () => {
    render(<Card aria-label="ліміти">{BODY}</Card>)
    const card = screen.getByRole('region', { name: 'ліміти' })
    expect(card.tagName).toBe('SECTION')
    expect(card).toHaveClass('rounded-card', 'border-line', 'bg-card')
    expect(card).not.toHaveClass('lift')
  })

  it('opts into the hover lift (reduced motion handled by the lift utility)', () => {
    render(<Card as="article" lift>{BODY}</Card>)
    expect(screen.getByRole('article')).toHaveClass('lift')
  })

  it('hero variant uses the gradient token', () => {
    const { container } = render(<Card as="div" variant="hero">{BODY}</Card>)
    expect(container.firstElementChild).toHaveClass('bg-(image:--tj-hero-gradient)')
    expect(container.firstElementChild).not.toHaveClass('bg-card')
  })
})

describe('Tile', () => {
  it.each([
    ['neutral', 'bg-track'],
    ['profit', 'bg-profit-wash'],
    ['loss', 'bg-loss-wash'],
    ['accent', 'bg-lavender-soft'],
    ['peach', 'bg-peach-soft'],
  ] as const)('%s tone -> %s', (tone, cls) => {
    render(<Tile tone={tone}>{BODY}</Tile>)
    expect(screen.getByText(BODY)).toHaveClass('rounded-tile', cls)
  })
})

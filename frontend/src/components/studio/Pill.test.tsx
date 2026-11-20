import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HeaderChip, Pill } from './Pill'

const COUNT = '12'
const PNL = '+68'
const SESSION = 'NY'
const THREE = '3'
const BIAS = 'біас'

describe('Pill', () => {
  it.each([
    ['neutral', ['bg-surface', 'text-ink', 'border-line']],
    ['profit', ['bg-profit-soft', 'text-profit']],
    ['loss', ['bg-loss-soft', 'text-loss']],
    ['accent', ['bg-lavender-soft', 'text-lavender']],
    ['peach', ['bg-peach-soft', 'text-ink']],
    ['warning', ['bg-warning-soft', 'text-warning', 'border-warning-border']],
  ] as const)('%s tone: soft background + own text colour', (tone, classes) => {
    render(<Pill tone={tone}>{COUNT}</Pill>)
    const pill = screen.getByText(COUNT)
    expect(pill).toHaveClass('rounded-full', ...classes)
    // Contrast rule: muted text never sits on a soft tone background.
    expect(pill).not.toHaveClass('text-muted-foreground')
    expect(pill).not.toHaveClass('text-ink-muted')
  })

  it('mono pills use tabular monospace digits', () => {
    render(<Pill mono>{PNL}</Pill>)
    expect(screen.getByText(PNL)).toHaveClass('num')
  })

  it('a status dot is decorative and uses the strong shade', () => {
    const { container } = render(
      <Pill tone="profit" dot>
        {SESSION}
      </Pill>,
    )
    expect(container.querySelector('[aria-hidden]')).toHaveClass('bg-profit-strong')
  })

  it('passes accessible attributes through', () => {
    render(<Pill aria-label="3 угоди чекають">{THREE}</Pill>)
    expect(screen.getByLabelText('3 угоди чекають')).toHaveTextContent(THREE)
  })
})

describe('HeaderChip', () => {
  it('is a medium pill', () => {
    render(<HeaderChip tone="loss">{BIAS}</HeaderChip>)
    expect(screen.getByText(BIAS)).toHaveClass('px-3', 'text-[13px]', 'bg-loss-soft')
  })
})

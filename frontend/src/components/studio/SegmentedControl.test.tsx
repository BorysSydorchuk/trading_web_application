import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { setupUser } from '@/test/user'
import { SegmentedControl } from './SegmentedControl'

const OPTIONS = [
  { value: 'week', label: 'Тиждень' },
  { value: 'month', label: 'Місяць' },
  { value: 'all', label: 'Усе' },
] as const
type Range = (typeof OPTIONS)[number]['value']

function Harness({ onChange }: { onChange?: (value: Range) => void }) {
  const [value, setValue] = useState<Range>('month')
  return (
    <SegmentedControl
      label="Період"
      value={value}
      options={OPTIONS}
      onChange={(next) => {
        setValue(next)
        onChange?.(next)
      }}
    />
  )
}

const radio = (name: string) => screen.getByRole('radio', { name })

describe('SegmentedControl', () => {
  it('is a named radio group with one checked option and one tab stop', () => {
    render(<Harness />)
    expect(screen.getByRole('radiogroup', { name: 'Період' })).toBeInTheDocument()
    expect(radio('Місяць')).toBeChecked()
    expect(radio('Місяць')).toHaveAttribute('tabindex', '0')
    expect(radio('Тиждень')).toHaveAttribute('tabindex', '-1')
    expect(radio('Місяць')).toHaveClass('bg-surface', 'font-semibold')
  })

  it('selects on click', async () => {
    const onChange = vi.fn()
    const user = setupUser()
    render(<Harness onChange={onChange} />)
    await user.click(radio('Усе'))
    expect(onChange).toHaveBeenCalledWith('all')
    expect(radio('Усе')).toBeChecked()
  })

  it('moves and selects with arrows, Home and End (wrapping)', async () => {
    const user = setupUser()
    render(<Harness />)
    await user.tab()
    expect(radio('Місяць')).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(radio('Усе')).toBeChecked()
    expect(radio('Усе')).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(radio('Тиждень')).toBeChecked()
    await user.keyboard('{ArrowLeft}')
    expect(radio('Усе')).toBeChecked()
    await user.keyboard('{Home}')
    expect(radio('Тиждень')).toHaveFocus()
    await user.keyboard('{End}')
    expect(radio('Усе')).toBeChecked()
  })

  it('turns transitions off under reduced motion', () => {
    render(<Harness />)
    expect(radio('Місяць')).toHaveClass('motion-reduce:transition-none')
  })

  it('checks nothing when the value is not an option; the first option keeps the tab stop', () => {
    render(<SegmentedControl label="Період" value="year" options={[...OPTIONS, { value: 'other', label: 'Інше' }]} onChange={() => undefined} />)
    for (const name of ['Тиждень', 'Місяць', 'Усе', 'Інше']) expect(radio(name)).not.toBeChecked()
    expect(radio('Тиждень')).toHaveAttribute('tabindex', '0')
    expect(radio('Місяць')).toHaveAttribute('tabindex', '-1')
  })
})

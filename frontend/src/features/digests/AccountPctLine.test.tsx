import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { AccountPctLine } from './AccountPctLine'

describe('digest «P&L рахунків»: both percents for «Усі рахунки» (PM 2026-11-27)', () => {
  it('shows the size-weighted and the equal-weighted percent', () => {
    render(<AccountPctLine block={{ accounts: 2, size_weighted: '1.3333', equal_weighted: '1.5000' }} />)
    expect(screen.getByTestId('digest-account-pct')).toHaveTextContent(uk.digests.accountPct.sizeWeighted)
    expect(screen.getByTestId('digest-account-pct')).toHaveTextContent(uk.digests.accountPct.equalWeighted)
    expect(screen.getByTestId('digest-pct-size')).toHaveTextContent('1.33')
    expect(screen.getByTestId('digest-pct-equal')).toHaveTextContent('1.5')
  })

  it('one account or an older snapshot: nothing new', () => {
    const { container } = render(<AccountPctLine block={{ accounts: 1, size_weighted: '1.5000', equal_weighted: '1.5000' }} />)
    expect(container).toBeEmptyDOMElement()
    render(<AccountPctLine block={undefined} />)
    expect(screen.queryByTestId('digest-account-pct')).not.toBeInTheDocument()
  })

  it('no usable size: an empty dash', () => {
    render(<AccountPctLine block={{ accounts: 2, size_weighted: null, equal_weighted: null }} />)
    expect(screen.getByTestId('digest-pct-size')).toHaveTextContent(uk.common.empty)
  })
})

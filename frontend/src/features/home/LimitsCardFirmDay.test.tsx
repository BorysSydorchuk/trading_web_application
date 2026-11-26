import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { homeLimits } from './home.fixture'
import { LimitsCard } from './LimitsCard'
import type { FirmAlert, FirmDay, HomeLimits } from './types'

const t = uk.home.limits

function firmDay(overrides: Partial<FirmDay> = {}): FirmDay {
  // 00:00 server time (UTC+2) = 22:00 UTC = 23:00 Brussels (CET, November).
  return {
    reset_at: '2026-11-25T22:00:00Z', start_balance: '100250.00', floor: '96250.00', loss_pct: '-4.00',
    pnl_pct: '-1.25', room_pct: '2.75', breached: false, to_verify: [], ...overrides,
  }
}

function renderCard(fd: FirmDay | null | undefined) {
  render(<LimitsCard limits={homeLimits({ firm_day: fd })} accountCount={1} accountId={1} />)
}

describe('LimitsCard «Денний ліміт фірми»', () => {
  it('shows the firm day bar, room and Brussels reset time', () => {
    renderCard(firmDay())
    const row = screen.getByTestId('firm-day')
    expect(row).toHaveTextContent(t.firmDay)
    expect(row).toHaveTextContent('−1.3%')
    // Room 2.75 is rounded down, never up; pnl −1.25 keeps the normal overview rounding.
    expect(row).toHaveTextContent('до ліміту 2.7%')
    expect(row).not.toHaveTextContent('2.8%')
    expect(row).toHaveTextContent('день фірми з 23:00')
    expect(screen.getByRole('img', { name: t.firmBarLabel('−1.3%', '−4%') })).toBeInTheDocument()
    expect(screen.queryByTestId('firm-day-breached')).not.toBeInTheDocument()
    expect(screen.queryByTestId('firm-day-no-floating')).not.toBeInTheDocument()
    expect(screen.queryByTestId('firm-day-verify')).not.toBeInTheDocument()
  })

  it.each([null, undefined])('has no firm row without firm_day (%s)', (fd) => {
    renderCard(fd)
    expect(screen.queryByTestId('firm-day')).not.toBeInTheDocument()
    expect(screen.getAllByTestId('limit-bar')).toHaveLength(3)
  })

  it('turns red with the breached message', () => {
    renderCard(firmDay({ pnl_pct: '-4.10', room_pct: '-0.10', breached: true }))
    expect(screen.getByTestId('firm-day-breached')).toHaveTextContent(t.firmBreached)
    expect(screen.getByText('−4.1%')).toHaveClass('text-loss')
  })

  it('shows «—» and the unknown floating hint when pnl and room are unknown', () => {
    renderCard(firmDay({ pnl_pct: null, room_pct: null }))
    expect(screen.getByTestId('firm-day')).toHaveTextContent(t.firmRoom(uk.common.empty))
    expect(screen.getByTestId('firm-day-no-floating')).toHaveTextContent(t.firmNoFloating)
    expect(screen.getByTestId('firm-day-bar').querySelector('[data-testid="limit-fill"]')).toHaveClass('hidden')
  })

  it.each([
    ['2.79', '2.7%'],
    ['2.70', '2.7%'],
    ['0.05', '0%'],
    ['-0.15', '−0.2%'],
    ['-0.10', '−0.1%'],
  ])('rounds the room %s down to «%s»', (room, shown) => {
    renderCard(firmDay({ room_pct: room }))
    expect(screen.getByTestId('firm-day')).toHaveTextContent(t.firmRoom(shown))
  })

  it('lists the items to verify', () => {
    renderCard(firmDay({ to_verify: ['daily_basis', 'daily_reset'] }))
    expect(screen.getByTestId('firm-day-verify')).toHaveTextContent('перевірити: база денного ліміту, час скидання дня')
  })
})

function renderAlert(alert: FirmAlert | null, accountId: number | null = 1, extra: Partial<HomeLimits> = {}) {
  render(<LimitsCard limits={homeLimits({ firm_alert: alert, ...extra })} accountCount={2} accountId={accountId} />)
}

describe('LimitsCard firm_alert', () => {
  it('firm day: red card and a red line with the room rounded down', () => {
    renderAlert({ kind: 'firm_day', room_pct: '0.89' })
    expect(screen.getByTestId('firm-alert')).toHaveTextContent(t.firmAlert(t.firmAlertKinds.firm_day, t.firmRoom('0.8%')))
    expect(screen.getByTestId('firm-alert')).toHaveTextContent('Близько до ліміту фірми: денний ліміт фірми, до ліміту 0.8%')
    const card = screen.getByRole('region', { name: t.title })
    expect(card).toHaveClass('border-loss')
    expect(card).toHaveAttribute('data-firm-alert', 'firm_day')
  })

  it('max loss: names the firm max loss', () => {
    renderAlert({ kind: 'max_loss', room_pct: '0.50' })
    expect(screen.getByTestId('firm-alert')).toHaveTextContent('Близько до ліміту фірми: макс. збиток фірми, до ліміту 0.5%')
  })

  it('room null: «ліміт досягнуто»', () => {
    renderAlert({ kind: 'max_loss', room_pct: null })
    expect(screen.getByTestId('firm-alert')).toHaveTextContent(t.firmAlert(t.firmAlertKinds.max_loss, t.firmAlertHit))
  })

  it.each([null, undefined])('no alert (%s): calm card, no red line', (alert) => {
    render(<LimitsCard limits={homeLimits({ firm_alert: alert })} accountCount={2} accountId={null} />)
    expect(screen.queryByTestId('firm-alert')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: t.title })).not.toHaveClass('border-loss')
    expect(screen.getByText(`Funded · ${t.closest}`)).toBeInTheDocument()
  })

  it('«Усі рахунки»: the closest suffix names the firm limit for an alerted account', () => {
    renderAlert({ kind: 'firm_day', room_pct: '0.30' }, null)
    expect(screen.getByText(`Funded · ${t.closestFirm}`)).toBeInTheDocument()
    expect(screen.queryByText(`Funded · ${t.closest}`)).not.toBeInTheDocument()
  })

  it('a single chosen account has no closest suffix even with an alert', () => {
    renderAlert({ kind: 'firm_day', room_pct: '0.30' }, 1)
    expect(screen.queryByText(new RegExp(t.closestFirm))).not.toBeInTheDocument()
  })

  it('empty to_verify shows no «перевірити» line in the firm day row', () => {
    renderAlert(null, 1, { firm_day: firmDay({ to_verify: [] }) })
    expect(screen.getByTestId('firm-day')).not.toHaveTextContent(t.firmVerify(''))
    expect(screen.queryByTestId('firm-day-verify')).not.toBeInTheDocument()
  })
})

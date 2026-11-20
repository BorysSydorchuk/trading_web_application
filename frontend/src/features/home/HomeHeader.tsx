import { useId } from 'react'
import { Link } from 'react-router'
import { HeaderChip } from '@/components/studio/Pill'
import { NativeSelect } from '@/components/ui/native-select'
import { uk } from '@/i18n/uk'
import { brusselsToday } from '@/lib/time'
import { cn } from '@/lib/utils'
import { brusselsHeaderDate, brusselsHourMinute } from './dates'
import type { HomeBiasToday, HomeSession } from './types'

const h = uk.home.header
const CHIP_LINK = 'rounded-full outline-none focus-visible:ring-[3px] focus-visible:ring-ring'

function directionWord(direction: string): string {
  const words: Record<string, string> = uk.bias.directions
  return words[direction] ?? direction
}

function LondonChip({ bias, newHref }: { bias: HomeBiasToday['pre_london']; newHref: string }) {
  if (bias === null) {
    // Missing bias is a system state: warning tone, never red (DESIGN_SYSTEM.md warning set).
    return (
      <Link to={newHref} className={CHIP_LINK}>
        <HeaderChip tone="warning">{h.londonMissing}</HeaderChip>
      </Link>
    )
  }
  if (bias.length === 0) return <HeaderChip>{h.londonEmpty}</HeaderChip>
  const text = bias.map((b) => `${b.symbol} ${h.arrows[b.direction] ?? ''}`.trim()).join(' ')
  const spoken = bias.map((b) => `${b.symbol} ${directionWord(b.direction)}`).join(', ')
  return (
    <HeaderChip aria-label={h.londonLabel(spoken)} title={h.londonLabel(spoken)}>
      {h.london(text)}
    </HeaderChip>
  )
}

export interface HomeAccountOption {
  id: number
  name: string
}

/** Account scope of the whole page, styled as a header chip (shown with more than one account). */
function AccountChip({ accounts, accountId, onAccount }: { accounts: readonly HomeAccountOption[]; accountId: number | null; onAccount: (id: number | null) => void }) {
  const id = useId()
  return (
    <>
      <label htmlFor={id} className="sr-only">
        {h.account}
      </label>
      <NativeSelect
        id={id}
        wrapperClassName="w-auto"
        className="h-auto rounded-full border-line bg-surface py-1.5 pr-8 pl-3 text-[13px] font-semibold text-ink shadow-none dark:bg-surface"
        value={accountId === null ? '' : String(accountId)}
        onChange={(e) => onAccount(e.target.value === '' ? null : Number(e.target.value))}
      >
        <option value="">{h.allAccounts}</option>
        {accounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </NativeSelect>
    </>
  )
}

export interface HomeHeaderProps {
  /** Server time (ISO UTC); the browser clock until the first answer. */
  now: string
  session: HomeSession | null
  bias: HomeBiasToday | null
  /** Active accounts; the account chip is shown with more than one. */
  accounts: readonly HomeAccountOption[]
  /** null = all accounts. Scopes the hero chart, KPIs, limits and bottom charts (not open positions). */
  accountId: number | null
  onAccount: (accountId: number | null) => void
}

/** Date · time (Brussels), account chip, session chip, today's London bias, «+ Біас NY», «Калькулятор». */
export function HomeHeader({ now, session, bias, accounts, accountId, onAccount }: HomeHeaderProps) {
  const today = brusselsToday(new Date(now))
  const sessionName = session ? h.sessions[session.key] : null
  return (
    <header className="flex flex-wrap items-center justify-between gap-3.5">
      <div>
        <p className="text-[13px] text-ink-muted">{h.dateTime(brusselsHeaderDate(now), brusselsHourMinute(now))}</p>
        <h1 className="type-page-title mt-1">{uk.home.title}</h1>
      </div>
      <nav aria-label={h.chips} className="flex flex-wrap items-center gap-2">
        {accounts.length > 1 && <AccountChip accounts={accounts} accountId={accountId} onAccount={onAccount} />}
        {session && sessionName && (
          <HeaderChip tone={session.entries_allowed ? 'profit' : 'neutral'} dot>
            {h.session(sessionName, session.entries_allowed ? h.entriesAllowed : h.entriesForbidden)}
          </HeaderChip>
        )}
        {bias && <LondonChip bias={bias.pre_london} newHref={`/bias/new?kind=pre_london&date=${today}`} />}
        {bias?.pre_ny_missing && (
          <Link to={`/bias/new?kind=pre_ny&date=${today}`} aria-label={h.biasNyLabel} className={CHIP_LINK}>
            <HeaderChip tone="warning">{h.biasNy}</HeaderChip>
          </Link>
        )}
        <Link
          to="/calculator"
          className={cn(
            'rounded-xl bg-lavender-button px-4 py-2 text-[13px] font-semibold text-lavender outline-none',
            'hover:bg-lavender-button-hover focus-visible:ring-[3px] focus-visible:ring-ring',
          )}
        >
          {h.calculator}
        </Link>
      </nav>
    </header>
  )
}

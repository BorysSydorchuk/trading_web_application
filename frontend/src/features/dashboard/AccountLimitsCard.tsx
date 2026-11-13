import { pnlClass } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { formatAccountMoney, formatLimit, formatPct } from './format'
import type { DashboardAccount, LimitState, PeriodBlock } from './types'

const a = uk.dashboard.accounts

function StateBadge({ state }: { state: LimitState }) {
  return (
    <span
      className={cn(
        'inline-block rounded px-1.5 py-0.5 text-xs whitespace-nowrap',
        state === 'ok' ? 'text-muted-foreground' : 'border border-loss bg-loss/15 font-semibold text-loss',
      )}
    >
      {a.states[state]}
    </span>
  )
}

interface RowProps {
  label: string
  block: PeriodBlock
  currency: string
  loss: string | null
  profit: string | null
  state: LimitState
}

const TD = 'num py-1.5 pr-3 text-right'

function PeriodRow({ label, block, currency, loss, profit, state }: RowProps) {
  return (
    <tr className="border-t">
      <th scope="row" className="py-1.5 pr-3 text-left font-normal text-muted-foreground">{label}</th>
      <td className={cn(TD, pnlClass(block.pnl))}>{formatAccountMoney(block.pnl, currency)}</td>
      <td className={cn(TD, pnlClass(block.pct))}>{formatPct(block.pct)}</td>
      <td className={cn(TD, 'text-muted-foreground')}>{formatLimit(loss)}</td>
      <td className={cn(TD, 'text-muted-foreground')}>{formatLimit(profit)}</td>
      <td className="py-1.5 text-right"><StateBadge state={state} /></td>
    </tr>
  )
}

const TH = 'pb-1 pr-3 text-right font-medium'

/** Today's and this week's P&L of one account vs its stop limits (all % of the account size). */
export function AccountLimitsCard({ account }: { account: DashboardAccount }) {
  const { limits } = account
  return (
    <article aria-label={account.name} className="flex flex-col gap-2 rounded-lg border p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{account.name}</h3>
        <span className="num text-xs text-muted-foreground">
          {a.size(formatAccountMoney(account.account_size, account.currency))}
        </span>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="pb-1 pr-3 text-left font-medium">{a.period}</th>
              <th scope="col" className={TH}>{a.pnl}</th>
              <th scope="col" className={TH}>{a.pct}</th>
              <th scope="col" className={TH}>{a.lossLimit}</th>
              <th scope="col" className={TH}>{a.profitLimit}</th>
              <th scope="col" className="pb-1 text-right font-medium">{a.state}</th>
            </tr>
          </thead>
          <tbody>
            <PeriodRow
              label={a.today}
              block={account.today}
              currency={account.currency}
              loss={limits.daily_loss_pct}
              profit={limits.daily_profit_pct}
              state={account.today_state}
            />
            <PeriodRow
              label={a.week}
              block={account.week}
              currency={account.currency}
              loss={limits.weekly_loss_pct}
              profit={limits.weekly_profit_pct}
              state={account.week_state}
            />
          </tbody>
        </table>
      </div>
    </article>
  )
}

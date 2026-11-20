import { Link } from 'react-router'
import { formatPct } from '@/features/dashboard/format'
import { formatSignedMoney, pnlClass } from '@/features/trades/format'
import { describePath } from '@/features/trades/links'
import { uk } from '@/i18n/uk'
import { formatShortDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { ROW, TABLE_CARD, THEAD } from './tableStyles'
import type { ExcludedBlock } from './types'

const x = uk.digests.excluded
const TH = 'px-4 py-2 font-medium whitespace-nowrap'
const TD = 'px-4 py-1.5 whitespace-nowrap'

function money(value: string, currency: string | null): string {
  const text = formatSignedMoney(value)
  return currency ? `${text} ${currency}` : text
}

/**
 * M8-01 «Виключені угоди: N, P&L X»: the excluded trades themselves (count, their P&L, list). The
 * account total with them is a separate line under the strategy result (`AccountTotalLine`).
 */
export function ExcludedTrades({ block, currency }: { block: ExcludedBlock; currency: string | null }) {
  if (block.trades === 0) return null
  return (
    <section aria-labelledby="digest-excluded" className="flex flex-col gap-2">
      <h2 id="digest-excluded" className="type-card-title m-0 text-ink">
        {x.summary(block.trades, money(block.net_pnl, currency))}
      </h2>
      <p className="text-xs text-ink-muted">{x.hint}</p>
      <div className={TABLE_CARD}>
        <table aria-label={x.title} className="w-full text-sm">
          <thead className={THEAD}>
            <tr>
              <th scope="col" className={`${TH} text-left`}>{x.date}</th>
              <th scope="col" className={`${TH} text-left`}>{x.account}</th>
              <th scope="col" className={`${TH} text-left`}>{x.symbol}</th>
              <th scope="col" className={`${TH} text-right`}>{uk.digests.withCurrency(x.pnl, currency)}</th>
              <th scope="col" className={`${TH} text-left`}>{x.reason}</th>
            </tr>
          </thead>
          <tbody>
            {block.items.map((item) => (
              <tr key={item.trade_id} className={ROW}>
                <td className={`${TD} num`}>{formatShortDateTimeBrussels(item.close_time)}</td>
                <td className={TD}>{item.account_name ?? uk.common.empty}</td>
                <td className={`${TD} num`}>
                  <Link to={describePath(item.trade_id)} className="type-symbol text-lavender underline-offset-2 hover:underline">
                    {item.symbol}
                  </Link>
                </td>
                <td className={cn(`${TD} num text-right`, pnlClass(item.net_pnl))}>{formatSignedMoney(item.net_pnl)}</td>
                <td className="px-4 py-1.5 break-words">{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/**
 * «Разом по рахунках (з виключеними)» under the strategy result (PM 2026-11-20): strategy P&L +
 * excluded P&L, same % base as Home, so it matches «Головна». Only when something is excluded.
 */
export function AccountTotalLine({ block, currency }: { block: ExcludedBlock; currency: string | null }) {
  if (block.trades === 0) return null
  return (
    <p data-testid="digest-account-total" className="text-sm">
      {x.accountTotal}:{' '}
      <span className={cn('num font-semibold', pnlClass(block.account_net_pnl))}>{money(block.account_net_pnl, currency)}</span>
      {block.account_net_pnl_pct != null && (
        <span data-testid="excluded-account-pct" className={cn('num ml-1', pnlClass(block.account_net_pnl_pct))}>
          {x.accountPct(formatPct(block.account_net_pnl_pct))}
        </span>
      )}
    </p>
  )
}

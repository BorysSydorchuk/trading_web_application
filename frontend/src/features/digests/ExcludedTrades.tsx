import { Link } from 'react-router'
import { formatSignedMoney, pnlClass } from '@/features/trades/format'
import { describePath } from '@/features/trades/links'
import { uk } from '@/i18n/uk'
import { formatShortDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import type { ExcludedBlock } from './types'

const x = uk.digests.excluded
const TH = 'px-3 py-1.5 font-medium whitespace-nowrap'
const TD = 'px-3 py-1 whitespace-nowrap'

function money(value: string, currency: string | null): string {
  const text = formatSignedMoney(value)
  return currency ? `${text} ${currency}` : text
}

/**
 * M8-01 «Виключені угоди: N, P&L X»: trades left out of the strategy numbers above, listed so the
 * digest still reconciles with the account (strategy P&L + excluded = account P&L).
 */
export function ExcludedTrades({ block, currency }: { block: ExcludedBlock; currency: string | null }) {
  if (block.trades === 0) return null
  return (
    <section aria-labelledby="digest-excluded" className="flex flex-col gap-2">
      <h2 id="digest-excluded" className="text-sm font-semibold">
        {x.summary(block.trades, money(block.net_pnl, currency))}
      </h2>
      <p className="text-xs text-muted-foreground">
        {x.hint}{' '}
        <span>
          {x.accountTotal}:{' '}
          <span className={cn('num font-medium', pnlClass(block.account_net_pnl))}>
            {money(block.account_net_pnl, currency)}
          </span>
        </span>
      </p>
      <div className="overflow-x-auto rounded-lg border">
        <table aria-label={x.title} className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
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
              <tr key={item.trade_id} className="border-t">
                <td className={`${TD} num`}>{formatShortDateTimeBrussels(item.close_time)}</td>
                <td className={TD}>{item.account_name ?? uk.common.empty}</td>
                <td className={`${TD} num`}>
                  <Link to={describePath(item.trade_id)} className="underline-offset-2 hover:underline">
                    {item.symbol}
                  </Link>
                </td>
                <td className={cn(`${TD} num text-right`, pnlClass(item.net_pnl))}>{formatSignedMoney(item.net_pnl)}</td>
                <td className="px-3 py-1 break-words">{item.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

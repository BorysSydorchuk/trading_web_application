import { formatPct } from '@/features/dashboard/format'
import { pnlClass } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import type { AccountPctBlock } from './types'

const t = uk.digests.accountPct

function Value({ pct, testId }: { pct: string | null; testId: string }) {
  return (
    <span data-testid={testId} className={cn('num font-semibold', pct !== null && pnlClass(pct))}>
      {pct === null ? uk.common.empty : formatPct(pct)}
    </span>
  )
}

/**
 * «Усі рахунки» (PM 2026-11-27): the accounts' P&L % of the summed sizes and the average of the
 * per-account % (the «Головна» rule), so one of them always matches Home. Hidden for one account.
 */
export function AccountPctLine({ block }: { block: AccountPctBlock | undefined }) {
  if (!block || block.accounts < 2) return null
  return (
    <div data-testid="digest-account-pct" className="flex flex-col gap-0.5 text-sm">
      <p className="flex flex-wrap gap-x-4">
        <span className="text-ink-muted">{t.title}:</span>
        <span>
          {t.sizeWeighted} <Value pct={block.size_weighted} testId="digest-pct-size" />
        </span>
        <span>
          {t.equalWeighted} <Value pct={block.equal_weighted} testId="digest-pct-equal" />
        </span>
      </p>
      <p className="text-xs text-ink-muted">{t.hint}</p>
    </div>
  )
}

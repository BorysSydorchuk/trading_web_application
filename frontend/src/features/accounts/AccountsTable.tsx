import type { ReactNode } from 'react'
import { KeyRound, Pencil, Trash2, TriangleAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { formatDecimal } from '@/lib/decimal'
import { formatRecentBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import type { Account } from './types'

const c = uk.accounts.columns

interface AccountsTableProps {
  accounts: Account[]
  onEdit: (account: Account) => void
  onDelete: (account: Account) => void
}

export function AccountsTable({ accounts, onEdit, onDelete }: AccountsTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:font-medium [&>th]:whitespace-nowrap">
            <th className="text-left">{c.name}</th>
            <th className="text-left">{c.firm}</th>
            <th className="text-left">{c.program}</th>
            <th className="text-left">{c.phase}</th>
            <th className="text-right">{c.login}</th>
            <th className="text-left">{c.server}</th>
            <th className="text-left">{c.status}</th>
            <th className="text-right">{c.accountSize}</th>
            <th className="text-right">{c.balance}</th>
            <th className="text-left">{c.currency}</th>
            <th className="text-left">{c.password}</th>
            <th className="text-right">
              <span className="sr-only">{c.actions}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((account) => (
            <AccountRow
              key={account.id}
              account={account}
              onEdit={() => onEdit(account)}
              onDelete={() => onDelete(account)}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface AccountRowProps {
  account: Account
  onEdit: () => void
  onDelete: () => void
}

function AccountRow({ account, onEdit, onDelete }: AccountRowProps) {
  const archived = account.status === 'archived'
  return (
    <tr
      className={cn(
        'border-t align-top hover:bg-muted/30 [&>td]:px-3 [&>td]:py-2',
        archived && 'text-muted-foreground',
      )}
    >
      <td className="font-medium whitespace-nowrap">{account.name}</td>
      <td className="whitespace-nowrap">{account.firm}</td>
      <td className="whitespace-nowrap">{account.program}</td>
      <td className="whitespace-nowrap">{uk.accounts.phase[account.phase]}</td>
      <td className="num text-right">{account.login}</td>
      <td className="whitespace-nowrap">{account.server}</td>
      <td className="whitespace-nowrap">{uk.accounts.status[account.status]}</td>
      <td className="num text-right whitespace-nowrap">{formatDecimal(account.reference_balance)}</td>
      <td className="text-right whitespace-nowrap">
        <BalanceCell account={account} />
      </td>
      <td className="num">{account.currency}</td>
      <td className="whitespace-nowrap">
        <PasswordCell account={account} />
      </td>
      <td className="text-right whitespace-nowrap">
        <div className="flex justify-end gap-1">
          <IconButton label={`${uk.accounts.actions.edit}: ${account.name}`} onClick={onEdit}>
            <Pencil />
          </IconButton>
          <IconButton label={`${uk.accounts.actions.delete}: ${account.name}`} onClick={onDelete}>
            <Trash2 />
          </IconButton>
        </div>
      </td>
    </tr>
  )
}

function BalanceCell({ account }: { account: Account }) {
  if (account.balance === null) {
    return <span className="text-xs text-muted-foreground">{uk.accounts.balanceNotSynced}</span>
  }
  return (
    <div className="flex flex-col items-end">
      <span className="num">{formatDecimal(account.balance)}</span>
      {account.balance_synced_at && (
        <span className="text-xs text-muted-foreground">
          {uk.accounts.balanceUpdated}{' '}
          <span className="num">{formatRecentBrussels(account.balance_synced_at)}</span>
        </span>
      )}
    </div>
  )
}

function PasswordCell({ account }: { account: Account }) {
  const p = uk.accounts.password
  return (
    <div className="flex flex-col">
      <span className="flex items-center gap-1.5">
        {account.password_configured ? (
          <KeyRound className="size-3.5 text-muted-foreground" aria-hidden />
        ) : (
          <TriangleAlert className="size-3.5 text-amber-400" aria-hidden />
        )}
        {account.password_configured ? p.configured : p.missing}
      </span>
      <span className="text-xs text-muted-foreground">
        {p.keyLabel} <span className="num">{account.password_env_key}</span>
      </span>
    </div>
  )
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-7"
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      {children}
    </Button>
  )
}

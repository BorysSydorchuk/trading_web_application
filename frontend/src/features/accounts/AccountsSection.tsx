import { useId, useState } from 'react'
import { Info, Loader2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { AccountFormDialog } from './AccountFormDialog'
import { AccountsTable } from './AccountsTable'
import { useAccounts } from './api'
import { DeleteAccountDialog } from './DeleteAccountDialog'
import type { Account } from './types'

const t = uk.accounts

/** Settings → "Рахунки": list, create/edit, delete/archive (PRD 6.1). */
export function AccountsSection() {
  const archivedToggleId = useId()
  const [includeArchived, setIncludeArchived] = useState(false)
  const { data, isPending, isError, error, refetch, isFetching } = useAccounts(includeArchived)

  // Kept separately from `open` so the dialog content does not change during the close animation.
  const [formOpen, setFormOpen] = useState(false)
  const [formAccount, setFormAccount] = useState<Account | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteAccount, setDeleteAccount] = useState<Account | null>(null)

  function openCreate() {
    setFormAccount(null)
    setFormOpen(true)
  }

  function openEdit(account: Account) {
    setFormAccount(account)
    setFormOpen(true)
  }

  function openDelete(account: Account) {
    setDeleteAccount(account)
    setDeleteOpen(true)
  }

  let body
  if (isPending) {
    body = <LoadingRows />
  } else if (isError) {
    body = (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
        <p>{t.loadError}</p>
        <p className="text-xs text-muted-foreground">{errorText(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching && <Loader2 className="animate-spin" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  } else if (data.items.length === 0) {
    body = (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
        <p className="text-muted-foreground">{t.empty}</p>
        <Button size="sm" onClick={openCreate}>
          <Plus aria-hidden />
          {t.add}
        </Button>
      </div>
    )
  } else {
    body = <AccountsTable accounts={data.items} onEdit={openEdit} onDelete={openDelete} />
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby={`${archivedToggleId}-title`}>
      <div className="flex flex-wrap items-center gap-4">
        <h2 id={`${archivedToggleId}-title`} className="text-base font-semibold">
          {t.title}
        </h2>
        {isFetching && !isPending && (
          <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden />
        )}
        <label
          htmlFor={archivedToggleId}
          className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted-foreground select-none"
        >
          <input
            id={archivedToggleId}
            type="checkbox"
            className="size-3.5 accent-primary"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          {t.showArchived}
        </label>
        <Button size="sm" onClick={openCreate}>
          <Plus aria-hidden />
          {t.add}
        </Button>
      </div>

      <PasswordInfo />

      {body}

      <AccountFormDialog open={formOpen} onOpenChange={setFormOpen} account={formAccount} />
      <DeleteAccountDialog open={deleteOpen} onOpenChange={setDeleteOpen} account={deleteAccount} />
    </section>
  )
}

function PasswordInfo() {
  const i = t.info
  return (
    <aside className="flex gap-3 rounded-lg border bg-muted/30 px-4 py-3 text-xs text-muted-foreground">
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        <p className="font-medium text-foreground">{i.title}</p>
        <p>{i.neverHere}</p>
        <p>
          {i.addLine} <code className="num rounded bg-muted px-1 py-0.5 text-foreground">{i.envExample}</code>{' '}
          {i.restart}
        </p>
        <p>{i.docs}</p>
      </div>
    </aside>
  )
}

function LoadingRows() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label={t.loading}>
      {[0, 1, 2].map((row) => (
        <div key={row} className="h-10 animate-pulse rounded-md bg-muted/50" />
      ))}
      <span className="sr-only">{t.loading}</span>
    </div>
  )
}

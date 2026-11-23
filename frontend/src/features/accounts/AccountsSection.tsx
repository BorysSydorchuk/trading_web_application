import { useEffect, useId, useState } from 'react'
import { Info, Loader2, Plus, Unplug } from 'lucide-react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { useCtraderStatus } from '@/features/ctrader/api'
import { DisconnectCtraderDialog } from '@/features/ctrader/DisconnectCtraderDialog'
import { cleanedOauthParams, readOauthReturn } from '@/features/ctrader/oauthReturn'
import { NOTICE_BOX_CLASS } from '@/features/journal/tableStyles'
import { ctraderErrorText, errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { AccountFormDialog } from './AccountFormDialog'
import { AccountsTable } from './AccountsTable'
import { useAccounts } from './api'
import { DeleteAccountDialog } from './DeleteAccountDialog'
import { StartingBalanceSuggestions } from './StartingBalanceSuggestions'
import type { Account, AccountPlatform } from './types'

const t = uk.accounts

/** Settings → "Рахунки": list, create/edit, delete/archive (PRD 6.1). */
export function AccountsSection() {
  const archivedToggleId = useId()
  const [includeArchived, setIncludeArchived] = useState(false)
  const { data, isPending, isError, error, refetch, isFetching } = useAccounts(includeArchived)
  // Only asked when the active list is empty: tells "no accounts" from "all archived".
  const probeEnabled = !includeArchived && data !== undefined && data.items.length === 0
  const archivedProbe = useAccounts(true, { enabled: probeEnabled })
  const allArchived =
    !includeArchived &&
    data?.items.length === 0 &&
    archivedProbe.data !== undefined &&
    archivedProbe.data.items.length > 0

  // Kept separately from `open` so the dialog content does not change during the close animation.
  // The cTrader sign-in is a full page load back to /settings, so the first render sees its result.
  const [searchParams, setSearchParams] = useSearchParams()
  const [returnedConnected] = useState(() => readOauthReturn(searchParams)?.ok === true)
  const [formOpen, setFormOpen] = useState(returnedConnected)
  const [formAccount, setFormAccount] = useState<Account | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteAccount, setDeleteAccount] = useState<Account | null>(null)
  const [formPlatform, setFormPlatform] = useState<AccountPlatform | null>(returnedConnected ? 'ctrader' : null)
  const [disconnectOpen, setDisconnectOpen] = useState(false)
  const ctraderStatus = useCtraderStatus()
  // Expired or rejected tokens are still stored, so they can be forgotten too.
  const canDisconnect =
    ctraderStatus.data !== undefined &&
    (ctraderStatus.data.connected ||
      ctraderStatus.data.error_code === 'token_expired' ||
      ctraderStatus.data.error_code === 'token_invalid')

  // One-time result in the query string: tell the user, then remove it from the address.
  useEffect(() => {
    const result = readOauthReturn(searchParams)
    if (!result) return
    // Fixed toast id: a repeated effect (StrictMode) does not stack a second message.
    if (result.ok) {
      toast(uk.ctrader.oauth.connected, { id: 'ctrader-oauth' })
    } else {
      toast.error(ctraderErrorText(result.code), { id: 'ctrader-oauth' })
    }
    setSearchParams(cleanedOauthParams(searchParams), { replace: true })
  }, [searchParams, setSearchParams])

  function openCreate() {
    setFormAccount(null)
    setFormPlatform(null)
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
  if (isPending || (probeEnabled && archivedProbe.isPending)) {
    body = <LoadingRows />
  } else if (isError) {
    body = (
      <div role="alert" className={cn(NOTICE_BOX_CLASS, 'flex flex-col items-center gap-3')}>
        <p>{t.loadError}</p>
        <p className="text-xs text-muted-foreground">{errorText(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching && <Loader2 className="animate-spin" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  } else if (allArchived) {
    body = (
      <div className={cn(NOTICE_BOX_CLASS, 'flex flex-col items-center gap-3')}>
        <p className="text-muted-foreground">{t.allArchived}</p>
        <Button variant="outline" size="sm" onClick={() => setIncludeArchived(true)}>
          {t.showArchived}
        </Button>
      </div>
    )
  } else if (data.items.length === 0) {
    body = (
      <div className={cn(NOTICE_BOX_CLASS, 'flex flex-col items-center gap-3')}>
        <p className="text-muted-foreground">{t.empty}</p>
        <Button size="sm" onClick={openCreate}>
          <Plus aria-hidden />
          {t.add}
        </Button>
      </div>
    )
  } else {
    body = (
      <>
        <StartingBalanceSuggestions accounts={data.items} />
        <AccountsTable accounts={data.items} onEdit={openEdit} onDelete={openDelete} />
      </>
    )
  }

  return (
    <section className="flex flex-col gap-3" aria-labelledby={`${archivedToggleId}-title`}>
      <SectionHeader
        id={`${archivedToggleId}-title`}
        title={t.title}
        actions={
          <HeaderActions
            id={archivedToggleId}
            checked={includeArchived}
            onToggle={setIncludeArchived}
            onAdd={openCreate}
            onDisconnect={canDisconnect ? () => setDisconnectOpen(true) : null}
          />
        }
      >
        {isFetching && !isPending && (
          <Loader2 className="size-4 animate-spin text-muted-foreground motion-reduce:animate-none" aria-hidden />
        )}
      </SectionHeader>

      <PasswordInfo />

      {body}

      <AccountFormDialog open={formOpen} onOpenChange={setFormOpen} account={formAccount} initialPlatform={formPlatform} />
      <DisconnectCtraderDialog open={disconnectOpen} onOpenChange={setDisconnectOpen} />
      <DeleteAccountDialog open={deleteOpen} onOpenChange={setDeleteOpen} account={deleteAccount} />
    </section>
  )
}

interface HeaderActionsProps {
  id: string
  checked: boolean
  onToggle: (checked: boolean) => void
  onAdd: () => void
  /** null = no stored cTrader connection to forget. */
  onDisconnect: (() => void) | null
}

function HeaderActions({ id, checked, onToggle, onAdd, onDisconnect }: HeaderActionsProps) {
  return (
    <>
      <label htmlFor={id} className="mr-2 flex cursor-pointer items-center gap-2 text-xs text-muted-foreground select-none">
        <input
          id={id}
          type="checkbox"
          className="size-3.5 accent-lavender-mid"
          checked={checked}
          onChange={(e) => onToggle(e.target.checked)}
        />
        {t.showArchived}
      </label>
      {onDisconnect && (
        <Button size="sm" variant="outline" onClick={onDisconnect}>
          <Unplug aria-hidden />
          {uk.ctrader.disconnect.action}
        </Button>
      )}
      <Button size="sm" onClick={onAdd}>
        <Plus aria-hidden />
        {t.add}
      </Button>
    </>
  )
}

function PasswordInfo() {
  const i = t.info
  return (
    <aside className="flex gap-3 rounded-card border border-line bg-card px-5 py-4 text-xs text-muted-foreground">
      <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        <p className="font-medium text-foreground">{i.title}</p>
        <p>{i.neverHere}</p>
        <p>
          {i.addLine} <code className="num rounded-md bg-track px-1.5 py-0.5 text-foreground">{i.envExample}</code>{' '}
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
        <div key={row} className="h-10 animate-pulse rounded-tile bg-muted motion-reduce:animate-none" />
      ))}
      <span className="sr-only">{t.loading}</span>
    </div>
  )
}

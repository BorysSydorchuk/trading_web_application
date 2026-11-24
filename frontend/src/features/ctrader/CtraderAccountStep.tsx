import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { isApiError } from '@/api/client'
import { Pill } from '@/components/studio/Pill'
import { Button } from '@/components/ui/button'
import { DialogClose, DialogFooter } from '@/components/ui/dialog'
import { uk } from '@/i18n/uk'
import { ctraderErrorText, errorText, showErrorToast } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { useConnectCtrader, useCtraderAccounts, useCtraderStatus } from './api'
import type { CtraderAccountItem } from './types'

const t = uk.ctrader.flow

/** API errors that a new sign-in fixes. */
const RECONNECT_CODES: ReadonlySet<string> = new Set([
  'ctrader_token_expired',
  'ctrader_token_invalid',
  'ctrader_not_authorized',
  'ctrader_trade_scope_refused',
])

interface CtraderAccountStepProps {
  onBack: () => void
  onPick: (account: CtraderAccountItem) => void
}

/** Add flow, cTrader path: not configured → not connected → pick an account. */
export function CtraderAccountStep({ onBack, onPick }: CtraderAccountStepProps) {
  const status = useCtraderStatus()
  const { isError: statusFailed, error: statusError } = status

  // The status query is silent for Settings; here the failure is the user's current action.
  useEffect(() => {
    if (statusFailed) showErrorToast(statusError)
  }, [statusFailed, statusError])

  let body
  if (status.isPending) {
    body = <Loading label={t.loadingStatus} />
  } else if (status.isError) {
    body = (
      <ErrorBox title={t.statusError} detail={errorText(status.error)} retrying={status.isFetching} onRetry={() => void status.refetch()} />
    )
  } else if (!status.data.configured) {
    body = <NotConfigured />
  } else if (!status.data.connected) {
    body = <NotConnected errorCode={status.data.error_code} />
  } else {
    return <AccountPicker onBack={onBack} onPick={onPick} />
  }

  return (
    <div className="flex flex-col gap-4">
      {body}
      <StepFooter onBack={onBack} />
    </div>
  )
}

function StepFooter({ onBack, children }: { onBack: () => void; children?: React.ReactNode }) {
  return (
    <DialogFooter>
      <Button type="button" variant="ghost" className="sm:mr-auto" onClick={onBack}>
        {t.back}
      </Button>
      <DialogClose asChild>
        <Button type="button" variant="outline">
          {uk.common.cancel}
        </Button>
      </DialogClose>
      {children}
    </DialogFooter>
  )
}

function Loading({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
      {label}
    </p>
  )
}

interface ErrorBoxProps {
  title: string
  detail: string
  retrying: boolean
  onRetry: () => void
}

function ErrorBox({ title, detail, retrying, onRetry }: ErrorBoxProps) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-md border border-destructive/50 px-3 py-3 text-sm">
      <p className="text-destructive">{title}</p>
      <p className="text-xs text-muted-foreground">{detail}</p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
        {retrying && <Loader2 className="animate-spin" aria-hidden />}
        {uk.common.retry}
      </Button>
    </div>
  )
}

function NotConfigured() {
  return (
    <div role="status" className="flex flex-col gap-2 rounded-md border border-line px-3 py-3 text-sm">
      <p className="font-medium text-foreground">{t.notConfiguredTitle}</p>
      <p className="text-muted-foreground">{t.notConfiguredLead}</p>
      <code className="num rounded-md bg-track px-2 py-1 text-xs text-foreground">{t.envClientId}</code>
      <code className="num rounded-md bg-track px-2 py-1 text-xs text-foreground">{t.envClientSecret}</code>
      <p className="text-muted-foreground">{t.notConfiguredRestart}</p>
    </div>
  )
}

function ConnectButton() {
  const connect = useConnectCtrader()
  // After success the browser is leaving the page: keep the button busy until it does.
  const busy = connect.isPending || connect.isSuccess
  return (
    <Button type="button" size="sm" onClick={() => connect.mutate()} disabled={busy}>
      {busy && <Loader2 className="animate-spin" aria-hidden />}
      {busy ? t.connecting : t.connect}
    </Button>
  )
}

function NotConnected({ errorCode }: { errorCode: string | null }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-md border border-line px-3 py-3 text-sm">
      <p className="font-medium text-foreground">{t.notConnectedTitle}</p>
      {errorCode ? (
        <p role="alert" className="text-destructive">
          {ctraderErrorText(errorCode)}
        </p>
      ) : (
        <p className="text-muted-foreground">{t.notConnectedText}</p>
      )}
      <ConnectButton />
    </div>
  )
}

function AccountPicker({ onBack, onPick }: CtraderAccountStepProps) {
  const accounts = useCtraderAccounts(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selected = accounts.data?.items.find(
    (item) => item.ctid_trader_account_id === selectedId && isSelectable(item),
  )

  let body
  if (accounts.isPending) {
    body = <Loading label={t.loadingAccounts} />
  } else if (accounts.isError) {
    const needsReconnect = isApiError(accounts.error) && RECONNECT_CODES.has(accounts.error.code)
    body = (
      <>
        <ErrorBox
          title={t.accountsError}
          detail={errorText(accounts.error)}
          retrying={accounts.isFetching}
          onRetry={() => void accounts.refetch()}
        />
        {needsReconnect && <ConnectButton />}
      </>
    )
  } else if (accounts.data.items.length === 0) {
    body = <p className="py-6 text-center text-sm text-muted-foreground">{t.empty}</p>
  } else {
    body = (
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-2 text-xs font-semibold tracking-wide text-foreground uppercase">{t.pickLegend}</legend>
        {accounts.data.items.map((item) => (
          <AccountOption
            key={item.ctid_trader_account_id}
            item={item}
            checked={item.ctid_trader_account_id === selectedId}
            onSelect={() => setSelectedId(item.ctid_trader_account_id)}
          />
        ))}
      </fieldset>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {body}
      <StepFooter onBack={onBack}>
        <Button type="button" disabled={!selected} onClick={() => selected && onPick(selected)}>
          {t.next}
        </Button>
      </StepFooter>
    </div>
  )
}

function isSelectable(item: CtraderAccountItem): boolean {
  return !item.already_added && item.trader_login !== null
}

interface AccountOptionProps {
  item: CtraderAccountItem
  checked: boolean
  onSelect: () => void
}

function AccountOption({ item, checked, onSelect }: AccountOptionProps) {
  const disabled = !isSelectable(item)
  const note = item.already_added ? t.alreadyAdded : item.trader_login === null ? t.noLogin : null
  return (
    <label
      className={cn(
        'flex items-center gap-3 rounded-md border border-line px-3 py-2 text-sm',
        disabled ? 'cursor-not-allowed text-muted-foreground' : 'cursor-pointer hover:bg-accent/60',
        checked && 'border-lavender-mid',
      )}
    >
      <input
        type="radio"
        name="ctrader-account"
        className="size-3.5 accent-lavender-mid"
        checked={checked}
        disabled={disabled}
        onChange={onSelect}
      />
      <span className="num">{item.trader_login ?? uk.common.empty}</span>
      <span className="min-w-0 flex-1 truncate">{item.broker}</span>
      {note && <span className="text-xs text-muted-foreground">{note}</span>}
      <Pill tone="neutral">{item.is_live ? t.live : t.demo}</Pill>
    </label>
  )
}

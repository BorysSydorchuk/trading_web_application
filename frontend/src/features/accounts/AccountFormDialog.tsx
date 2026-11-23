import { useIsMutating } from '@tanstack/react-query'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { uk } from '@/i18n/uk'
import { AccountForm, AccountFormHeader } from './AccountForm'
import { AddAccountFlow } from './AddAccountFlow'
import { accountKeys } from './api'
import type { Account, AccountPlatform } from './types'

interface AccountFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** null = create a new account. */
  account: Account | null
  /** Skips the platform choice (the return from cTrader sign-in). */
  initialPlatform?: AccountPlatform | null
}

export function AccountFormDialog({ open, onOpenChange, account, initialPlatform = null }: AccountFormDialogProps) {
  const isSaving = useIsMutating({ mutationKey: accountKeys.save }) > 0
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Escape / outside click / close button must not drop a save in flight.
        if (!isSaving) onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        {/* Mounted only while open, so every opening starts from fresh state. */}
        {account ? (
          <>
            <AccountFormHeader title={uk.accounts.form.editTitle} />
            <AccountForm account={account} onDone={() => onOpenChange(false)} />
          </>
        ) : (
          <AddAccountFlow initialPlatform={initialPlatform} onDone={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

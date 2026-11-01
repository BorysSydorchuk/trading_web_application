import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { uk } from '@/i18n/uk'
import { useDeleteAccount, type DeleteOutcome } from './api'
import type { Account } from './types'

const t = uk.accounts.deleteDialog

const outcomeText: Record<DeleteOutcome, string> = {
  deleted: t.deleted,
  archived: t.archived,
  unknown: t.done,
}

interface DeleteAccountDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  account: Account | null
}

/** In-app confirmation (no window.confirm). Accounts with trades are archived by the backend. */
export function DeleteAccountDialog({ open, onOpenChange, account }: DeleteAccountDialogProps) {
  const deleteMutation = useDeleteAccount()

  function handleConfirm() {
    if (!account) return
    deleteMutation.mutate(account.id, {
      onSuccess: (outcome) => {
        toast(outcomeText[outcome])
        onOpenChange(false)
      },
    })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!deleteMutation.isPending) onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.title}</DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-col gap-2">
              {account && (
                <p className="text-foreground">
                  {account.name}
                  <span className="text-muted-foreground">
                    {' · '}
                    <span className="num">{account.login}</span>
                    {' · '}
                    {account.server}
                  </span>
                </p>
              )}
              <p>{t.archiveNote}</p>
              <p>{t.deleteNote}</p>
            </div>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={deleteMutation.isPending}>
              {uk.common.cancel}
            </Button>
          </DialogClose>
          <Button
            type="button"
            variant="destructive"
            onClick={handleConfirm}
            disabled={deleteMutation.isPending || !account}
          >
            {deleteMutation.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {deleteMutation.isPending ? t.deleting : t.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

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
import { useDisconnectCtrader } from './api'

const t = uk.ctrader.disconnect

interface DisconnectCtraderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** Forgets the stored tokens; accounts stay. A failure shows the global error toast. */
export function DisconnectCtraderDialog({ open, onOpenChange }: DisconnectCtraderDialogProps) {
  const disconnect = useDisconnectCtrader()

  function handleConfirm() {
    disconnect.mutate(undefined, {
      onSuccess: () => {
        toast(t.done)
        onOpenChange(false)
      },
    })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!disconnect.isPending) onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.title}</DialogTitle>
          <DialogDescription>{t.text}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={disconnect.isPending}>
              {uk.common.cancel}
            </Button>
          </DialogClose>
          <Button type="button" variant="destructive" onClick={handleConfirm} disabled={disconnect.isPending}>
            {disconnect.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {disconnect.isPending ? t.pending : t.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

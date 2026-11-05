import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { uk } from '@/i18n/uk'

const e = uk.bias.editor

interface DeleteBiasDialogProps {
  open: boolean
  deleting: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

/** In-app confirmation before DELETE /api/bias/notes/{id} (no window.confirm). */
export function DeleteBiasDialog({ open, deleting, onOpenChange, onConfirm }: DeleteBiasDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(next) => !deleting && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{e.deleteTitle}</DialogTitle>
          <DialogDescription>{e.deleteText}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={deleting}>
            {uk.common.cancel}
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={deleting}>
            {deleting && <Loader2 className="animate-spin" aria-hidden />}
            {deleting ? e.deleting : e.delete}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

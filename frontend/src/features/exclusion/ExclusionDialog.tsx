import { useId, useState } from 'react'
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
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useStatsExclusion } from '@/features/trades/api'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'

const t = uk.exclusion
/** Same limit as the API (docs/api.md M8-01). */
export const REASON_MAX_LENGTH = 1000

export interface ExclusionTarget {
  id: number
  symbol: string
  excluded_from_stats: boolean
}

interface ExclusionDialogProps {
  /** The trade to exclude (when counted) or return (when excluded); null = closed. */
  trade: ExclusionTarget | null
  onClose: () => void
}

/** M8-01: «Не враховувати у статистиці» with a mandatory reason, or «Повернути у статистику». */
export function ExclusionDialog({ trade, onClose }: ExclusionDialogProps) {
  return (
    <Dialog open={trade !== null} onOpenChange={(open) => !open && onClose()}>
      {/* Keyed by trade and mode: every opening starts with an empty reason. */}
      {trade && <ExclusionForm key={`${trade.id}-${trade.excluded_from_stats}`} trade={trade} onClose={onClose} />}
    </Dialog>
  )
}

function ExclusionForm({ trade, onClose }: { trade: ExclusionTarget; onClose: () => void }) {
  const id = useId()
  const mutation = useStatsExclusion()
  const [reason, setReason] = useState('')
  const [showMissing, setShowMissing] = useState(false)
  const excluding = !trade.excluded_from_stats
  const trimmed = reason.trim()
  const missing = excluding && trimmed === ''

  function submit(event: React.FormEvent) {
    event.preventDefault()
    if (missing) {
      setShowMissing(true)
      return
    }
    mutation.mutate(
      { id: trade.id, exclude: excluding, reason: trimmed === '' ? null : trimmed },
      {
        onSuccess: () => {
          toast(excluding ? t.excludedToast : t.includedToast)
          onClose()
        },
      },
    )
  }

  const invalid = showMissing && missing
  return (
    <DialogContent className="sm:max-w-md" onClick={(e) => e.stopPropagation()}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <DialogHeader>
          <DialogTitle>
            {excluding ? t.exclude : t.include}
            <span className="num text-muted-foreground"> · {trade.symbol}</span>
          </DialogTitle>
          <DialogDescription asChild>
            <div className="flex flex-col gap-2">
              <p>{excluding ? t.excludeHint : t.includeHint}</p>
              <p>{t.digestNote}</p>
            </div>
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-reason`}>{excluding ? t.reason : t.reasonOptional}</Label>
          <Textarea
            id={`${id}-reason`}
            value={reason}
            maxLength={REASON_MAX_LENGTH}
            placeholder={excluding ? t.reasonPlaceholder : undefined}
            aria-invalid={invalid || undefined}
            aria-describedby={invalid ? `${id}-missing` : undefined}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
          {invalid && (
            <p id={`${id}-missing`} className="text-xs text-destructive">
              {t.reasonRequired}
            </p>
          )}
          {mutation.isError && (
            <p role="alert" className="text-xs text-destructive">
              {errorText(mutation.error)}
            </p>
          )}
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={mutation.isPending}>
              {uk.common.cancel}
            </Button>
          </DialogClose>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {mutation.isPending ? t.saving : excluding ? t.exclude : t.include}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  )
}

import { useEffect, useId, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { uk } from '@/i18n/uk'
import { useSaveReview } from './api'
import { REVIEW_FIELDS, REVIEW_MAX_LENGTH, type Digest, type ReviewField, type ReviewInput } from './types'

const r = uk.digests.review

function initialReview(digest: Digest): ReviewInput {
  return {
    what_worked: digest.what_worked ?? '',
    what_to_fix: digest.what_to_fix ?? '',
    focus_next: digest.focus_next ?? '',
  }
}

interface ReviewFormProps {
  digest: Digest
  /** Unsaved edits, for the screen's unsaved-changes guard. */
  onDirtyChange: (dirty: boolean) => void
}

/** What worked / what to fix / focus next (all optional; any non-empty field = reviewed). PATCH on save. */
export function ReviewForm({ digest, onDirtyChange }: ReviewFormProps) {
  const id = useId()
  const [values, setValues] = useState<ReviewInput>(() => initialReview(digest))
  const [saved, setSaved] = useState<ReviewInput>(() => initialReview(digest))
  const save = useSaveReview(digest.id)
  const dirty = REVIEW_FIELDS.some((field) => values[field] !== saved[field])

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange])

  function setField(field: ReviewField, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  function submit() {
    const sent = values
    save.mutate(sent, { onSuccess: () => setSaved(sent) })
  }

  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`${id}-title`} className="text-sm font-semibold">{r.title}</h2>
        <span className="text-xs text-muted-foreground">{r.hint}</span>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {REVIEW_FIELDS.map((field) => (
          <div key={field} className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-${field}`} className="text-xs font-medium text-muted-foreground">
              {r[field]}
            </label>
            <Textarea
              id={`${id}-${field}`}
              value={values[field]}
              maxLength={REVIEW_MAX_LENGTH}
              rows={4}
              className="text-sm"
              onChange={(event) => setField(field, event.target.value)}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-end">
        <Button type="button" size="sm" onClick={submit} disabled={save.isPending || !dirty}>
          {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {save.isPending ? r.saving : r.save}
        </Button>
      </div>
    </section>
  )
}

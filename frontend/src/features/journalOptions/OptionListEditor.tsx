import { ArrowDown, ArrowUp, Eye, EyeOff, Loader2, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Card } from '@/components/studio/Card'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { parseSynonyms, useChangeOptions, useEditableOptions, type EditableOption, type OptionAction, type OptionChange } from './api'

const t = uk.journalOptions
const INPUT = 'h-8 w-full min-w-0 rounded-md border border-input bg-transparent px-2 text-sm'
const ICON_BUTTON =
  'inline-flex size-7 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40'

/** Resolves to whether the server accepted the change. */
type RunAction = (action: OptionAction) => Promise<boolean>

function moved(values: readonly string[], index: number, step: -1 | 1): string[] {
  const next = [...values]
  const [item] = next.splice(index, 1)
  if (item !== undefined) next.splice(index + step, 0, item)
  return next
}

/** One editable list. Reusable for any field the API manages (`MANAGED_FIELDS`). */
export function OptionListEditor({ field, title }: { field: string; title: string }) {
  const list = useEditableOptions(field)
  const change = useChangeOptions(field)
  const [saveError, setSaveError] = useState<unknown>(null)
  // Add, delete and reorder change the set or order the arrows and delete buttons rely on.
  const [listChanges, setListChanges] = useState(0)
  const moving = listChanges > 0
  const options = list.data?.options ?? []
  const values = options.map((option) => option.value)

  // Changes are queued (mutation scope), so a blur save never swallows the click that caused it.
  const run: RunAction = async (action) => {
    const changesList = action.kind !== 'update'
    setSaveError(null)
    if (changesList) setListChanges((n) => n + 1)
    try {
      await change.mutateAsync(action)
      return true
    } catch (error) {
      setSaveError(error)
      return false
    } finally {
      if (changesList) setListChanges((n) => n - 1)
    }
  }
  const move = (index: number, step: -1 | 1) => run({ kind: 'order', values: moved(values, index, step) })

  return (
    <Card className="flex flex-col gap-3">
      <h3 className="m-0 text-sm font-medium text-ink">{title}</h3>
      {list.isPending && (
        <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
          {t.loading}
        </div>
      )}
      {list.isError && (
        <p role="alert" className="text-sm text-destructive">
          {t.loadError} {errorText(list.error)}
        </p>
      )}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {options.map((option, index) => (
          <OptionRow
            key={option.value}
            option={option}
            isFirst={index === 0}
            isLast={index === options.length - 1}
            moving={moving}
            onAction={run}
            onMove={(step) => void move(index, step)}
          />
        ))}
      </ul>
      <AddOption onAdd={(label, synonyms) => run({ kind: 'add', label, synonyms })} />
      {saveError !== null && (
        <p role="alert" className="text-xs text-destructive">
          {t.saveError} {errorText(saveError)}
        </p>
      )}
    </Card>
  )
}

interface OptionRowProps {
  option: EditableOption
  isFirst: boolean
  isLast: boolean
  moving: boolean
  onAction: RunAction
  onMove: (step: -1 | 1) => void
}

/**
 * A draft lives only while it differs from the server: after the save settles it is dropped, so
 * the input shows what was stored (a rejected text returns to the saved value, the error is shown).
 */
function useDraft(saved: string, save: (text: string) => Promise<unknown> | null) {
  const [draft, setDraft] = useState<string | null>(null)
  const commit = () => {
    if (draft === null) return
    const pending = save(draft)
    if (pending === null) {
      setDraft(null)
      return
    }
    void pending.then(() => setDraft((current) => (current === draft ? null : current)))
  }
  return { value: draft ?? saved, change: setDraft, commit }
}

function OptionRow({ option, isFirst, isLast, moving, onAction, onMove }: OptionRowProps) {
  const savedSynonyms = option.synonyms.join(', ')
  const update = (change: OptionChange) => onAction({ kind: 'update', value: option.value, change })
  const label = useDraft(option.label, (text) => {
    const next = text.trim()
    return next === '' || next === option.label ? null : update({ label: next })
  })
  const synonyms = useDraft(savedSynonyms, (text) => {
    const next = parseSynonyms(text)
    return next.join(', ') === savedSynonyms ? null : update({ synonyms: next })
  })
  const used = option.used_count > 0

  return (
    <li className={`flex flex-col gap-1 rounded-md border border-border p-2 ${option.hidden ? 'opacity-60' : ''}`}>
      <div className="flex items-center gap-1">
        <button type="button" className={ICON_BUTTON} aria-label={t.moveUp(option.label)} disabled={moving || isFirst} onClick={() => onMove(-1)}>
          <ArrowUp className="size-4" aria-hidden />
        </button>
        <button type="button" className={ICON_BUTTON} aria-label={t.moveDown(option.label)} disabled={moving || isLast} onClick={() => onMove(1)}>
          <ArrowDown className="size-4" aria-hidden />
        </button>
        <input className={INPUT} aria-label={t.labelFor(option.label)} maxLength={60} value={label.value} onChange={(e) => label.change(e.target.value)} onBlur={label.commit} />
        <span className="num shrink-0 px-1 text-xs whitespace-nowrap text-ink-muted">{t.used(option.used_count)}</span>
        <button
          type="button"
          className={ICON_BUTTON}
          aria-label={option.hidden ? t.show(option.label) : t.hide(option.label)}
          aria-pressed={option.hidden}
          onClick={() => void update({ hidden: !option.hidden })}
        >
          {option.hidden ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
        </button>
        <button
          type="button"
          className={ICON_BUTTON}
          aria-label={t.remove(option.label)}
          title={used ? t.removeBlocked : undefined}
          disabled={used || moving}
          onClick={() => void onAction({ kind: 'delete', value: option.value })}
        >
          <Trash2 className="size-4" aria-hidden />
        </button>
      </div>
      <input
        className={INPUT}
        aria-label={t.synonymsFor(option.label)}
        placeholder={t.synonymsPlaceholder}
        value={synonyms.value}
        onChange={(e) => synonyms.change(e.target.value)}
        onBlur={synonyms.commit}
      />
    </li>
  )
}

function AddOption({ onAdd }: { onAdd: (label: string, synonyms: string[]) => Promise<boolean> }) {
  const [label, setLabel] = useState('')
  const [synonyms, setSynonyms] = useState('')
  const [adding, setAdding] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const name = label.trim()
    if (name === '' || adding) return
    setAdding(true)
    const saved = await onAdd(name, parseSynonyms(synonyms))
    setAdding(false)
    // A refused name stays in the form, so it can be corrected.
    if (saved) {
      setLabel('')
      setSynonyms('')
    }
  }
  return (
    <form className="flex flex-col gap-1 sm:flex-row" onSubmit={(event) => void submit(event)}>
      <input className={INPUT} aria-label={t.newLabel} placeholder={t.newLabel} maxLength={60} value={label} onChange={(e) => setLabel(e.target.value)} />
      <input className={INPUT} aria-label={t.newSynonyms} placeholder={t.synonymsPlaceholder} value={synonyms} onChange={(e) => setSynonyms(e.target.value)} />
      <button type="submit" disabled={adding || label.trim() === ''} className="h-8 shrink-0 rounded-md bg-primary px-3 text-sm text-primary-foreground disabled:opacity-50">
        {t.add}
      </button>
    </form>
  )
}

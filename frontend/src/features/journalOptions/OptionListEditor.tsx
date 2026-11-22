import { ArrowDown, ArrowUp, Eye, EyeOff, Loader2, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Card } from '@/components/studio/Card'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { parseSynonyms, useChangeOptions, useEditableOptions, type EditableOption, type OptionAction } from './api'

const t = uk.journalOptions
const INPUT = 'h-8 w-full min-w-0 rounded-md border border-input bg-transparent px-2 text-sm'
const ICON_BUTTON =
  'inline-flex size-7 shrink-0 items-center justify-center rounded-md text-ink-muted hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40'

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
  const options = list.data?.options ?? []
  const values = options.map((option) => option.value)

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
            // Remount on a saved change so the inputs show what the server stored.
            key={`${option.value}:${option.label}:${option.synonyms.join(',')}`}
            option={option}
            isFirst={index === 0}
            isLast={index === options.length - 1}
            busy={change.isPending}
            onAction={(action) => change.mutate(action)}
            onMove={(step) => change.mutate({ kind: 'order', values: moved(values, index, step) })}
          />
        ))}
      </ul>
      <AddOption busy={change.isPending} onAdd={(label, synonyms) => change.mutate({ kind: 'add', label, synonyms })} />
      {change.isError && (
        <p role="alert" className="text-xs text-destructive">
          {t.saveError} {errorText(change.error)}
        </p>
      )}
    </Card>
  )
}

interface OptionRowProps {
  option: EditableOption
  isFirst: boolean
  isLast: boolean
  busy: boolean
  onAction: (action: OptionAction) => void
  onMove: (step: -1 | 1) => void
}

function OptionRow({ option, isFirst, isLast, busy, onAction, onMove }: OptionRowProps) {
  const savedSynonyms = option.synonyms.join(', ')
  const [label, setLabel] = useState(option.label)
  const [synonyms, setSynonyms] = useState(savedSynonyms)
  const update = (change: { label?: string; hidden?: boolean; synonyms?: string[] }) =>
    onAction({ kind: 'update', value: option.value, change })
  const saveLabel = () => {
    const next = label.trim()
    if (next === '') setLabel(option.label)
    else if (next !== option.label) update({ label: next })
  }
  const saveSynonyms = () => {
    const next = parseSynonyms(synonyms)
    if (next.join(', ') !== savedSynonyms) update({ synonyms: next })
  }
  const used = option.used_count > 0

  return (
    <li className={`flex flex-col gap-1 rounded-md border border-border p-2 ${option.hidden ? 'opacity-60' : ''}`}>
      <div className="flex items-center gap-1">
        <button type="button" className={ICON_BUTTON} aria-label={t.moveUp(option.label)} disabled={busy || isFirst} onClick={() => onMove(-1)}>
          <ArrowUp className="size-4" aria-hidden />
        </button>
        <button type="button" className={ICON_BUTTON} aria-label={t.moveDown(option.label)} disabled={busy || isLast} onClick={() => onMove(1)}>
          <ArrowDown className="size-4" aria-hidden />
        </button>
        <input className={INPUT} aria-label={t.labelFor(option.label)} maxLength={60} value={label} onChange={(e) => setLabel(e.target.value)} onBlur={saveLabel} />
        <span className="num shrink-0 px-1 text-xs whitespace-nowrap text-ink-muted">{t.used(option.used_count)}</span>
        <button
          type="button"
          className={ICON_BUTTON}
          aria-label={option.hidden ? t.show(option.label) : t.hide(option.label)}
          aria-pressed={option.hidden}
          disabled={busy}
          onClick={() => update({ hidden: !option.hidden })}
        >
          {option.hidden ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
        </button>
        <button
          type="button"
          className={ICON_BUTTON}
          aria-label={t.remove(option.label)}
          title={used ? t.removeBlocked : undefined}
          disabled={busy || used}
          onClick={() => onAction({ kind: 'delete', value: option.value })}
        >
          <Trash2 className="size-4" aria-hidden />
        </button>
      </div>
      <input
        className={INPUT}
        aria-label={t.synonymsFor(option.label)}
        placeholder={t.synonymsPlaceholder}
        value={synonyms}
        onChange={(e) => setSynonyms(e.target.value)}
        onBlur={saveSynonyms}
      />
    </li>
  )
}

function AddOption({ busy, onAdd }: { busy: boolean; onAdd: (label: string, synonyms: string[]) => void }) {
  const [label, setLabel] = useState('')
  const [synonyms, setSynonyms] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const name = label.trim()
    if (name === '') return
    onAdd(name, parseSynonyms(synonyms))
    setLabel('')
    setSynonyms('')
  }
  return (
    <form className="flex flex-col gap-1 sm:flex-row" onSubmit={submit}>
      <input className={INPUT} aria-label={t.newLabel} placeholder={t.newLabel} maxLength={60} value={label} onChange={(e) => setLabel(e.target.value)} />
      <input className={INPUT} aria-label={t.newSynonyms} placeholder={t.synonymsPlaceholder} value={synonyms} onChange={(e) => setSynonyms(e.target.value)} />
      <button type="submit" disabled={busy || label.trim() === ''} className="h-8 shrink-0 rounded-md bg-primary px-3 text-sm text-primary-foreground disabled:opacity-50">
        {t.add}
      </button>
    </form>
  )
}

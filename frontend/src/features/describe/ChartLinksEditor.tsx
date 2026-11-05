import { useState, type ClipboardEvent } from 'react'
import { ExternalLink, Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import type { JournalField } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import {
  LINK_KINDS,
  MAX_CHART_LINKS,
  MAX_URL_LENGTH,
  hasBeforeLink,
  isValidChartUrl,
  newLinkRow,
  snapshotPreviewUrl,
  type LinkDraft,
  type LinkKind,
} from './chartLinks'
import { FieldShell } from './FieldControls'
import { fieldDomId } from './formModel'

const l = uk.describe.links

interface ChartLinksEditorProps {
  field: JournalField | undefined
  links: readonly LinkDraft[]
  errors: Readonly<Record<string, string>>
  missing: boolean
  onChange: (links: LinkDraft[]) => void
  /** DOM id key (several editors on one page need different ones). */
  fieldKey?: string
  /** Label when there is no journal field (default "Посилання на графік (TradingView)"). */
  label?: string
  /** Before/after select per row (off for bias links, which have one kind). */
  showKind?: boolean
}

/** Chart links: before/after, add/remove, thumbnail for snapshot links (docs/api.md chart_links). */
export function ChartLinksEditor(props: ChartLinksEditorProps) {
  const { field, links, errors, missing, onChange, fieldKey = 'chart_links', label = l.title, showKind = true } = props
  const kindLabel = (kind: string) => field?.options?.find((o) => o.value === kind)?.label ?? l.kinds[kind as LinkKind] ?? kind
  const canAdd = links.length < MAX_CHART_LINKS

  function update(rowId: string, patch: Partial<LinkDraft>) {
    onChange(links.map((link) => (link.rowId === rowId ? { ...link, ...patch, previewUrl: patch.url !== undefined ? null : link.previewUrl } : link)))
  }

  function add() {
    onChange([...links, newLinkRow('', hasBeforeLink(links) ? 'after' : 'before')])
  }

  /** Pasting several URLs at once (space or newline separated) creates one row per URL. */
  function handlePaste(event: ClipboardEvent<HTMLInputElement>, row: LinkDraft) {
    const parts = event.clipboardData.getData('text').split(/\s+/).filter(Boolean)
    if (parts.length < 2) return
    event.preventDefault()
    const room = MAX_CHART_LINKS - links.length + 1
    const [first = '', ...rest] = parts.slice(0, room)
    const extra = rest.map((url) => newLinkRow(url, row.kind))
    const index = links.findIndex((link) => link.rowId === row.rowId)
    const updated = links.map((link) => (link.rowId === row.rowId ? { ...link, url: first, previewUrl: null } : link))
    onChange([...updated.slice(0, index + 1), ...extra, ...updated.slice(index + 1)])
  }

  return (
    <FieldShell
      fieldKey={fieldKey}
      label={field?.label ?? label}
      required={field?.required === true}
      aiFilled={false}
      missing={missing}
      error={null}
      hint={field?.required ? l.requiredHint : undefined}
      group
    >
      <div id={fieldDomId(fieldKey)} className="flex flex-col gap-2">
        {links.length === 0 && <p className="text-xs text-muted-foreground">{l.empty}</p>}
        {links.map((link, index) => (
          <LinkRow
            key={link.rowId}
            link={link}
            index={index}
            error={errors[link.rowId] ?? null}
            kindLabel={kindLabel}
            showKind={showKind}
            onUrl={(url) => update(link.rowId, { url })}
            onKind={(kind) => update(link.rowId, { kind })}
            onRemove={() => onChange(links.filter((other) => other.rowId !== link.rowId))}
            onPaste={(event) => handlePaste(event, link)}
          />
        ))}
        <div className="flex items-center gap-3">
          <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={add} disabled={!canAdd}>
            <Plus aria-hidden />
            {l.add}
          </Button>
          {!canAdd && <span className="text-xs text-muted-foreground">{l.limit(MAX_CHART_LINKS)}</span>}
        </div>
      </div>
    </FieldShell>
  )
}

interface LinkRowProps {
  link: LinkDraft
  index: number
  error: string | null
  kindLabel: (kind: string) => string
  showKind: boolean
  onUrl: (url: string) => void
  onKind: (kind: LinkKind) => void
  onRemove: () => void
  onPaste: (event: ClipboardEvent<HTMLInputElement>) => void
}

function LinkRow({ link, index, error, kindLabel, showKind, onUrl, onKind, onRemove, onPaste }: LinkRowProps) {
  const url = link.url.trim()
  const valid = isValidChartUrl(url)
  const preview = valid ? (link.previewUrl ?? snapshotPreviewUrl(url)) : null
  const inputId = `chart-link-${link.rowId}`
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        {showKind && (
          <NativeSelect
            aria-label={l.kindLabel(index + 1)}
            className="h-7 w-36 text-xs"
            wrapperClassName="w-auto"
            value={link.kind}
            onChange={(e) => onKind(e.target.value as LinkKind)}
          >
            {LINK_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kindLabel(kind)}
              </option>
            ))}
          </NativeSelect>
        )}
        <Input
          id={inputId}
          aria-label={l.urlLabel(index + 1)}
          inputMode="url"
          spellCheck={false}
          autoComplete="off"
          maxLength={MAX_URL_LENGTH}
          placeholder={l.placeholder}
          className="h-7 flex-1 text-xs"
          value={link.url}
          aria-invalid={error ? true : undefined}
          onChange={(e) => onUrl(e.target.value)}
          onPaste={onPaste}
        />
        <Button type="button" variant="ghost" size="icon" className="size-7" aria-label={l.remove} onClick={onRemove}>
          <X aria-hidden />
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      {valid && <LinkPreview key={preview ?? url} url={url} preview={preview} />}
    </div>
  )
}

/** Snapshot thumbnail; a plain link when there is no preview or the image fails to load. */
function LinkPreview({ url, preview }: { url: string; preview: string | null }) {
  const [failed, setFailed] = useState(false)
  const showImage = preview !== null && !failed
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={cn('inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground', showImage && 'flex-col items-start')}
    >
      {showImage && (
        <img
          src={preview}
          alt={l.previewAlt}
          loading="lazy"
          referrerPolicy="no-referrer"
          className="h-24 w-auto rounded border object-cover"
          onError={() => setFailed(true)}
        />
      )}
      <span className="inline-flex items-center gap-1">
        <ExternalLink className="size-3" aria-hidden />
        {l.open}
      </span>
    </a>
  )
}

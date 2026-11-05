import { Link } from 'react-router'
import { uk } from '@/i18n/uk'
import { brusselsToday } from '@/lib/time'
import { BiasResultControl } from './BiasResultControl'
import { DirectionLabel } from './DirectionLabel'
import { canMarkResult, formatDayHeader, groupByDate, formatIsoDate, weekRange } from './period'
import type { BiasEntry, BiasNote } from './types'

const l = uk.bias.list

export function BiasNoteList({ notes }: { notes: readonly BiasNote[] }) {
  const today = brusselsToday()
  return (
    <div className="flex flex-col gap-4">
      {groupByDate(notes).map((group) => (
        <section key={group.date} aria-label={formatDayHeader(group.date)} className="flex flex-col gap-2">
          <h2 className="num text-xs font-medium text-muted-foreground">{formatDayHeader(group.date)}</h2>
          {group.notes.map((note) => (
            <NoteCard key={note.id} note={note} canMark={canMarkResult(note.period_date, today)} />
          ))}
        </section>
      ))}
    </div>
  )
}

function periodHint(note: BiasNote): string | null {
  if (note.kind !== 'weekly') return null
  const [from, to] = weekRange(note.period_date)
  return l.weekOf(from, to)
}

function NoteCard({ note, canMark }: { note: BiasNote; canMark: boolean }) {
  const kind = uk.bias.kinds[note.kind]
  const hint = periodHint(note)
  return (
    <article
      aria-label={l.noteLabel(kind, formatIsoDate(note.period_date))}
      className="flex flex-col gap-1.5 rounded-lg border px-3 py-2"
    >
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-semibold">{kind}</h3>
        {hint && <span className="num text-xs text-muted-foreground">{hint}</span>}
        <Link to={`/bias/${note.id}`} className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
          {l.open}
        </Link>
      </div>
      {note.entries.length === 0 ? (
        <p className="text-xs text-muted-foreground">{l.noEntries}</p>
      ) : (
        <ul aria-label={l.entriesLabel} className="flex flex-col divide-y divide-border/60">
          {note.entries.map((entry) => (
            <EntryRow key={entry.id} entry={entry} canMark={canMark} />
          ))}
        </ul>
      )}
    </article>
  )
}

function EntryRow({ entry, canMark }: { entry: BiasEntry; canMark: boolean }) {
  return (
    <li
      aria-label={entry.symbol}
      className="grid grid-cols-[5.5rem_9rem_5.5rem_minmax(0,1fr)_auto] items-center gap-3 py-1 text-xs"
    >
      <span className="num font-medium">{entry.symbol}</span>
      <DirectionLabel direction={entry.direction} />
      <span className="num text-muted-foreground">
        {entry.confidence === null ? l.noConfidence : l.confidence(entry.confidence)}
      </span>
      <span className="truncate" title={entry.key_levels ?? undefined}>
        {entry.key_levels ?? <span className="text-muted-foreground">{l.noLevels}</span>}
      </span>
      {canMark ? <BiasResultControl entry={entry} /> : <span />}
    </li>
  )
}

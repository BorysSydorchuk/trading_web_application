import { Loader2 } from 'lucide-react'
import { Card } from '@/components/studio/Card'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { useDesktopState, useSetDesktop, type DesktopChange, type DesktopState } from './api'

const t = uk.desktopSettings

/** Settings → «Запуск» (M8-12): autostart at Windows login and the MT5 terminal windows. */
export function DesktopSection() {
  const state = useDesktopState()
  const change = useSetDesktop()

  let body
  if (state.isPending) {
    body = (
      <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
        {t.loading}
      </div>
    )
  } else if (state.isError) {
    body = (
      <p role="alert" className="text-sm text-destructive">
        {t.loadError} {errorText(state.error)}
      </p>
    )
  } else if (!state.data.supported) {
    body = <p className="text-sm text-muted-foreground">{t.unsupported}</p>
  } else {
    body = <Toggles data={state.data} busy={change.isPending} onChange={(c) => change.mutate(c)} />
  }

  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title={t.title} />
      <Card className="flex flex-col gap-4">
        {body}
        {change.isError && (
          <p role="alert" className="text-xs text-destructive">
            {t.saveError} {errorText(change.error)}
          </p>
        )}
      </Card>
    </section>
  )
}

interface TogglesProps {
  data: DesktopState
  busy: boolean
  onChange: (change: DesktopChange) => void
}

function Toggles({ data, busy, onChange }: TogglesProps) {
  return (
    <>
      <label className="flex cursor-pointer items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 size-3.5 accent-lavender-mid"
          checked={data.autostart}
          disabled={busy}
          onChange={(e) => onChange({ autostart: e.target.checked })}
        />
        <span className="flex flex-col">
          <span>{t.autostart}</span>
          <span className="text-xs text-muted-foreground">{t.autostartHint}</span>
        </span>
      </label>
      <label className="flex cursor-pointer items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          className="mt-0.5 size-3.5 accent-lavender-mid"
          checked={data.terminals_visible}
          disabled={busy}
          onChange={(e) => onChange({ terminals_visible: e.target.checked })}
        />
        <span className="flex flex-col">
          <span>{t.terminals}</span>
          <span className="text-xs text-muted-foreground">{t.terminalsHint}</span>
        </span>
      </label>
    </>
  )
}

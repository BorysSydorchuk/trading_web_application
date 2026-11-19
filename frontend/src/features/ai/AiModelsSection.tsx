import { useId } from 'react'
import { Loader2 } from 'lucide-react'
import { NativeSelect } from '@/components/ui/native-select'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { CALL_TYPES, useAiModels, useSetAiDefaults, type CallType } from './models'

const t = uk.aiModels

/** Settings → «Моделі ШІ» (M8-13): the default model per call type. */
export function AiModelsSection() {
  const id = useId()
  const query = useAiModels()
  const save = useSetAiDefaults()

  let body
  if (query.isPending) {
    body = (
      <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t.loading}
      </div>
    )
  } else if (query.isError) {
    body = (
      <p role="alert" className="text-sm text-destructive">
        {t.loadError} {errorText(query.error)}
      </p>
    )
  } else {
    const data = query.data
    body = (
      <div className="grid gap-3 sm:grid-cols-3">
        {CALL_TYPES.map((callType: CallType) => (
          <div key={callType} className="flex flex-col gap-1">
            <label htmlFor={`${id}-${callType}`} className="text-xs font-medium text-muted-foreground">
              {t.callTypes[callType]}
            </label>
            <NativeSelect
              id={`${id}-${callType}`}
              className="h-8 text-xs"
              value={data.defaults[callType]}
              disabled={save.isPending}
              onChange={(e) => save.mutate({ [callType]: e.target.value })}
            >
              {data.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {t.option(m.label, m.approx_usd[callType])}
                </option>
              ))}
            </NativeSelect>
          </div>
        ))}
      </div>
    )
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">{t.title}</h2>
      <div className="flex flex-col gap-2 rounded-lg border px-4 py-3">
        <p className="text-xs text-muted-foreground">{t.hint}</p>
        {body}
        {save.isError && (
          <p role="alert" className="text-xs text-destructive">
            {t.saveError} {errorText(save.error)}
          </p>
        )}
      </div>
    </section>
  )
}

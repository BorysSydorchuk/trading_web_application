import { NativeSelect } from '@/components/ui/native-select'
import { uk } from '@/i18n/uk'
import type { OneOffModel } from './models'

const t = uk.aiModels

/** M8-13: the small model selector next to an AI button, with the approximate cost per call. */
export function ModelPicker({ models, callType, model, setModel, disabled }: OneOffModel & { disabled?: boolean }) {
  if (models.length === 0 || model === undefined) return null
  return (
    <NativeSelect
      aria-label={t.pickerLabel}
      className="h-8 text-xs"
      wrapperClassName="w-auto"
      value={model}
      disabled={disabled}
      onChange={(e) => setModel(e.target.value)}
    >
      {models.map((m) => (
        <option key={m.id} value={m.id}>
          {t.option(m.label, m.approx_usd[callType])}
        </option>
      ))}
    </NativeSelect>
  )
}

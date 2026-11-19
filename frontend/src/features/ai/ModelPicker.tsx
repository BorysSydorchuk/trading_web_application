import { NativeSelect } from '@/components/ui/native-select'
import { uk } from '@/i18n/uk'
import { isUnlisted, type OneOffModel } from './models'

const t = uk.aiModels

/** M8-13: the small model selector next to an AI button, with the approximate cost per call. */
export function ModelPicker({ models, callType, shown, setModel, disabled }: OneOffModel & { disabled?: boolean }) {
  if (models.length === 0 || shown === undefined) return null
  return (
    <NativeSelect
      aria-label={t.pickerLabel}
      className="h-8 text-xs"
      wrapperClassName="w-auto"
      value={shown}
      disabled={disabled}
      onChange={(e) => setModel(e.target.value)}
    >
      {isUnlisted(models, shown) && <option value={shown}>{t.envOption(shown)}</option>}
      {models.map((m) => (
        <option key={m.id} value={m.id}>
          {t.option(m.label, m.approx_usd[callType])}
        </option>
      ))}
    </NativeSelect>
  )
}

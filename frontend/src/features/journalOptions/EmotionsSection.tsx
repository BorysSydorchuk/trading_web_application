import { SectionHeader } from '@/components/studio/SectionHeader'
import { uk } from '@/i18n/uk'
import { OptionListEditor } from './OptionListEditor'

const t = uk.journalOptions

/** Settings → «Емоції»: the two independent lists of the journal emotion fields. */
export function EmotionsSection() {
  return (
    <section className="flex flex-col gap-3">
      <SectionHeader title={t.title} />
      <p className="m-0 text-xs text-muted-foreground">{t.hint}</p>
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <OptionListEditor field="emotion_before" title={t.before} />
        <OptionListEditor field="emotion_after" title={t.after} />
      </div>
    </section>
  )
}

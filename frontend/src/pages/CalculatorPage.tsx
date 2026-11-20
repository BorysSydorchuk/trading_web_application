import { CalculatorForm } from '@/features/calculator/CalculatorForm'
import { uk } from '@/i18n/uk'

/** /calculator: position-size calculator (PRD 6.8). */
export function CalculatorPage() {
  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col gap-1">
        <h1 className="type-page-title m-0 text-ink">{uk.pages.calculator.title}</h1>
        <p className="text-[13px] text-ink-muted">{uk.pages.calculator.description}</p>
      </div>
      <CalculatorForm />
    </section>
  )
}

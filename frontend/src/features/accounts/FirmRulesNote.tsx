import { firmRulesText } from './firmRules'
import type { FirmRules } from './types'

/** Effective firm rules under «Правила фірми» (source `firm` only; otherwise nothing). */
export function FirmRulesNote({ rules }: { rules: FirmRules | null | undefined }) {
  const text = firmRulesText(rules)
  if (text === null) return null
  return (
    <div data-testid="firm-rules-note" className="flex flex-col gap-1 rounded-md border border-border px-3 py-2 text-xs">
      <p>
        <span className="font-semibold text-foreground">{text.title}</span>{' '}
        <span className="text-muted-foreground">{text.summary}</span>
      </p>
      {text.verify.map((line) => (
        <p key={line} data-testid="firm-rules-verify" className="text-warning">
          {line}
        </p>
      ))}
    </div>
  )
}

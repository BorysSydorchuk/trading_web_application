/**
 * «Студія» tone classes (docs/design/DESIGN_SYSTEM.md). Soft background + its own text colour:
 * muted text is never placed on loss-soft or button backgrounds (DECISIONS 2026-11-20 contrast).
 * Green/red tones are for P&L, deviations and status only.
 */
export type Tone = 'neutral' | 'profit' | 'loss' | 'accent' | 'peach'

/** Pills and badges: soft fill + readable text. */
export const pillToneClass: Record<Tone, string> = {
  neutral: 'border border-line bg-surface text-ink',
  profit: 'bg-profit-soft text-profit',
  loss: 'bg-loss-soft text-loss',
  accent: 'bg-lavender-soft text-lavender',
  peach: 'bg-peach-soft text-ink',
}

/** Status dots (pills, footer): the strong shade of each tone. */
export const dotToneClass: Record<Tone, string> = {
  neutral: 'bg-faint',
  profit: 'bg-profit-strong',
  loss: 'bg-loss-strong',
  accent: 'bg-lavender-mid',
  peach: 'bg-warning-strong',
}

/** Tiles / inner boxes: a lighter wash, text stays ink. */
export const tileToneClass: Record<Tone, string> = {
  neutral: 'bg-track',
  profit: 'bg-profit-wash',
  loss: 'bg-loss-wash',
  accent: 'bg-lavender-soft',
  peach: 'bg-peach-soft',
}

export type KpiTone = 'profit' | 'loss' | 'accent' | 'neutral'

interface KpiToneClasses {
  /** Card background: tone wash fading to white. */
  card: string
  /** Selected ring (2px border). */
  ring: string
  /** Value colour. */
  value: string
}

/** KPI cards: P&L green, drawdown red on peach, rates/R lavender (mockup docs/design/home-mockup.html). */
export const kpiToneClass: Record<KpiTone, KpiToneClasses> = {
  profit: { card: 'bg-linear-160 from-profit-wash to-surface to-70%', ring: 'border-profit-mid', value: 'text-profit' },
  loss: { card: 'bg-linear-160 from-peach-soft to-surface to-70%', ring: 'border-loss-mid', value: 'text-loss' },
  accent: { card: 'bg-linear-160 from-lavender-soft to-surface to-70%', ring: 'border-lavender-ring', value: 'text-lavender' },
  neutral: { card: 'bg-surface', ring: 'border-lavender-ring', value: 'text-ink' },
}

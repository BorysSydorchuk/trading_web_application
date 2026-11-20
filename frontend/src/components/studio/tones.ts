/**
 * «Студія» tone classes (docs/design/DESIGN_SYSTEM.md). Soft background + its own text colour:
 * muted text is never placed on loss-soft or button backgrounds (DECISIONS 2026-11-20 contrast).
 * Green/red tones are for P&L, deviations and status only.
 */
export type Tone = 'neutral' | 'profit' | 'loss' | 'accent' | 'peach' | 'warning'

/** Pills and badges: soft fill + readable text. */
export const pillToneClass: Record<Tone, string> = {
  neutral: 'border border-line bg-surface text-ink',
  profit: 'bg-profit-soft text-profit',
  loss: 'bg-loss-soft text-loss',
  accent: 'bg-lavender-soft text-lavender',
  peach: 'bg-peach-soft text-ink',
  /** System states only (stale data, sync delay, missing bias); never P&L or risk. */
  warning: 'border border-warning-border bg-warning-soft text-warning',
}

/** Status dots (pills, footer): the strong shade of each tone. */
export const dotToneClass: Record<Tone, string> = {
  neutral: 'bg-faint',
  profit: 'bg-profit-strong',
  loss: 'bg-loss-strong',
  accent: 'bg-lavender-mid',
  peach: 'bg-warning-strong',
  warning: 'bg-warning-strong',
}

/** Tiles / inner boxes: a lighter wash, text stays ink. */
export const tileToneClass: Record<Tone, string> = {
  neutral: 'bg-track',
  profit: 'bg-profit-wash',
  loss: 'bg-loss-wash',
  accent: 'bg-lavender-soft',
  peach: 'bg-peach-soft',
  warning: 'bg-warning-soft',
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

/** KPI cards: P&L green, loss / near-limit red on peach, rates/R lavender (mockup docs/design/home-mockup.html). */
export const kpiToneClass: Record<KpiTone, KpiToneClasses> = {
  // Selected rings use the tone's text shade: >= 5.8:1 on the page and the card washes (WCAG 1.4.11
  // asks 3:1; the pastel -mid / accent-ring shades of the mockup were 1.6-2.3:1, M8-10a review gap).
  profit: { card: 'bg-linear-160 from-profit-wash to-surface to-70%', ring: 'border-profit', value: 'text-profit' },
  loss: { card: 'bg-linear-160 from-peach-soft to-surface to-70%', ring: 'border-loss', value: 'text-loss' },
  accent: { card: 'bg-linear-160 from-lavender-soft to-surface to-70%', ring: 'border-lavender', value: 'text-lavender' },
  neutral: { card: 'bg-surface', ring: 'border-lavender', value: 'text-ink' },
}

/**
 * Selected state of pressed toggle buttons (filters, presets, choice chips). The border is accent
 * text (>= 8.6:1 on every background; lavender-mid fails 3:1 on page and chrome) and the label goes
 * semibold, so selected differs from hover (`hover:bg-accent`, no border change) and from the
 * unselected `border-input` without relying on the pastel fill.
 */
export const selectedToggleClass = 'border-lavender bg-lavender-button font-semibold text-lavender'

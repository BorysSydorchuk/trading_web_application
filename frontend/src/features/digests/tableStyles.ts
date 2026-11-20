/**
 * «Студія» table classes shared by the digest tables (docs/design/DESIGN_SYSTEM.md): a white card
 * with the studio radius, muted header text, hairline row dividers. Numbers stay exact (tables).
 */

/** Scroll wrapper around a full-width table (list, excluded trades, rules). */
export const TABLE_CARD = 'overflow-x-auto rounded-card border border-line bg-card'

/** Table card holding a title row above the table (breakdowns, matrix). */
export const TITLED_TABLE_CARD = 'flex min-w-0 flex-col gap-1 rounded-card border border-line bg-card py-2'

/** Header row: muted small text, divider under it. */
export const THEAD = 'border-b border-line text-xs text-ink-muted'

/** Body row divider (the first row sits right under the header border). */
export const ROW = 'border-t border-divider first:border-t-0'

/** Small card title (Manrope) for blocks inside a section. */
export const BLOCK_TITLE = 'm-0 font-display text-sm font-extrabold text-ink'

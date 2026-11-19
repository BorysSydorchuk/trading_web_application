# «Студія» design system (M8-10a)

Light pastel theme for the Trading Journal. Source of truth for colours, type, shape, motion,
base components and display rounding. Reference mockup: `docs/design/home-mockup.html` (design-tool
file; layout reference only, its runtime and Google Fonts are not used by the app).
Decisions: `docs/DECISIONS.md` 2026-11-20 (display rounding, contrast rule, fonts).

## 1. Where things live

| What | File |
|---|---|
| Tokens (CSS variables), Tailwind mapping, type/motion utilities | `frontend/src/index.css` |
| Base components | `frontend/src/components/studio/*` |
| Tone class maps | `frontend/src/components/studio/tones.ts` |
| Button (shadcn, restyled) | `frontend/src/components/ui/button.tsx` |
| Display formatter | `frontend/src/lib/displayFormat.ts` |
| Screenshots of every page (1440 / 1280 px) | `docs/reports/M8-10a-screens/`, refresh with `npm run e2e:screens` in `frontend/` |

`index.css` has three layers:
1. **Raw palette** `--tj-*` in `:root` (the only values a theme changes).
2. **shadcn semantic variables** (`--background`, `--card`, `--primary`, `--muted`, `--border`, `--ring`, ...) pointing at `--tj-*`, so every existing page picks up the palette.
3. **Tailwind `@theme inline`** colour/radius/shadow/font names used in class names.

## 2. Colour tokens

| CSS variable | Tailwind name | Value | Use |
|---|---|---|---|
| `--tj-page` | `bg-page`, `bg-background` | `#F6F6F4` | Page background |
| `--tj-chrome` | `bg-chrome`, `bg-sidebar` | `#EFEFEC` | Sidebar, footer status bar |
| `--tj-surface` | `bg-surface`, `bg-card`, `bg-popover` | `#FFFFFF` | Cards, active sidebar item, pills (neutral) |
| `--tj-border` | `border-line`, `border-border` | `#E4E4E0` | Card and section borders |
| `--tj-input` | `border-input` | `#D6D6D0` | Form control borders, dashed "more" tiles (a step darker than card borders) |
| `--tj-divider` | `border-divider` | `#F0F0EC` | Row dividers inside cards |
| `--tj-track` | `bg-track`, `bg-muted`, `bg-secondary` | `#F1F1EE` | Progress/limit tracks, neutral tiles |
| `--tj-text` | `text-ink`, `text-foreground` | `#1F1F1F` | Main text |
| `--tj-muted` | `text-ink-muted`, `text-muted-foreground` | `#6A6A66` | Secondary and small text, chart labels |
| `--tj-faint` | `bg-faint`, `stroke-faint` | `#8A8A85` | **Non-text graphics only** (gridlines, ticks, zero lines, dashed borders, idle dots) |
| `--tj-profit-text` | `text-profit` | `#0E6B43` | P&L gain text |
| `--tj-profit-strong` | `bg-profit-strong`, `fill-`/`stroke-profit-strong` | `#2EA067` | Status dots, live dot, chart lines and bars (>= 3:1 on white) |
| `--tj-profit-mid` | `*-profit-mid` | `#7BCFA2` | Area fill, heatmap cells (ink text stays readable on them), selected KPI ring |
| `--tj-profit-light` | `*-profit-light` | `#CDEFD9` | Bar gradient end |
| `--tj-profit-soft` | `bg-profit-soft` | `#E3F4EA` | Profit pills |
| `--tj-profit-wash` | `bg-profit-wash` | `#EAF6EF` | Profit tiles, KPI wash |
| `--tj-loss-text` | `text-loss`, `text-destructive` | `#A3271F` | P&L loss text, errors |
| `--tj-loss-strong` | `bg-loss-strong`, `fill-`/`stroke-loss-strong` | `#E2665E` | Status dots (down), chart lines and bars |
| `--tj-loss-mid` | `*-loss-mid` | `#EE958E` | Heatmap cells, selected drawdown KPI ring |
| `--tj-loss-light` | `*-loss-light` | `#F8D2CE` | Bar gradient end, destructive button hover |
| `--tj-loss-soft` | `bg-loss-soft` | `#FBE3E1` | Loss pills, sidebar badges, destructive button |
| `--tj-loss-wash` | `bg-loss-wash` | `#FBEDEC` | Loss tiles |
| `--tj-accent-text` | `text-lavender`, `text-primary-foreground`, `text-ai`, `ring-ring`, `border-lavender` | `#3B2F86` | Accent text, links, primary button text, AI marks, **focus ring** (`--ring`), selected toggle border |
| `--tj-accent-mid` | `*-lavender-mid` | `#8E86D9` | Chart line start, checkboxes, progress bars |
| `--tj-accent-ring` | `border-lavender-ring` | `#B9B2EE` | Decorative borders (digest suggestion card, «не переглянуто» badge), selected KPI ring. Not a focus ring (1.97:1 on white) |
| `--tj-accent-soft` | `bg-lavender-soft`, `bg-accent` | `#F3F1FB` | Accent pills, hover background |
| `--tj-accent-button` | `bg-lavender-button`, `bg-primary` | `#E7E3FA` | Primary button, active filter |
| `--tj-accent-button-hover` | `bg-lavender-button-hover` | `#DCD6F7` | Primary button hover |
| `--tj-peach-soft` | `bg-peach-soft` | `#FCF2EA` | Peach pills/tiles, drawdown KPI wash |
| `--tj-warning-text` | `text-warning` | `#8A5300` | Warning text (sync, backup, AI key chips). Added in M8-10a: the old amber-400 was unreadable on light backgrounds |
| `--tj-warning-strong` | `bg-warning-strong` | `#E0A030` | Warning dots and borders |
| `--tj-hero-gradient` | `bg-(image:--tj-hero-gradient)` | `linear-gradient(135deg, #EAF6EF 0%, #F3F1FB 55%, #FCF2EA 100%)` | Home hero card (`<Card variant="hero">`) |
| `--tj-mark-gradient` | `bg-(image:--tj-mark-gradient)` | `linear-gradient(135deg, #CDEFD9 0%, #DCD6F7 100%)` | TJ mark in the sidebar |
| `--tj-chart-line-from` / `-to` | — | `#8E86D9` -> `#2EA067` | Main chart line gradient (left to right) |
| `--tj-chart-area` | — | `#7BCFA2` | Area fill, 45% opacity at the top to 0% at the base |

Rules: no black or dark buttons/badges. Green/red only for P&L, deviations and status. Status pills
are soft background + their own text colour. Chart marks use the -strong (lines, bars) or -mid
(heatmap cells under ink text) shades, never the -text shades.

## 3. Contrast (WCAG 2.x, AA = 4.5:1 for text)

| Text colour | page | chrome | surface | accent-soft | profit-soft | loss-soft | button | peach-soft | track |
|---|---|---|---|---|---|---|---|---|---|
| text `#1F1F1F` | 15.23 | 14.31 | 16.48 | 14.75 | 14.44 | 13.48 | 13.16 | 14.94 | 14.57 |
| muted `#6A6A66` | 5.02 | 4.71 | 5.43 | 4.86 | 4.76 | **4.44 FAIL** | **4.34 FAIL** | 4.92 | 4.80 |
| faint `#8A8A85` | **3.21** | **3.01** | **3.47** | **3.10** | **3.04** | **2.84** | **2.77** | **3.14** | **3.06** |
| profit `#0E6B43` | 6.06 | 5.69 | 6.56 | 5.87 | 5.74 | 5.36 | 5.23 | 5.94 | 5.79 |
| loss `#A3271F` | 6.77 | 6.36 | 7.32 | 6.55 | 6.42 | 5.99 | 5.85 | 6.64 | 6.47 |
| accent `#3B2F86` | 10.02 | 9.41 | 10.84 | 9.70 | 9.50 | 8.87 | 8.66 | 9.82 | 9.58 |
| warning `#8A5300` | 5.85 | 5.49 | 6.33 | 5.66 | 5.54 | 5.18 | 5.05 | 5.73 | 5.59 |

Rules (DECISIONS 2026-11-20):
- **faint** fails for text everywhere: use it only for non-text graphics.
- Small text, including chart labels and axis ticks, uses **muted**.
- **muted** never sits on loss-soft or button backgrounds; those use their own text colours
  (loss text, accent text).
- Non-text contrast (WCAG 1.4.11, 3:1). Measured graphics colours:

  | Graphic colour | white | page | chrome | accent-soft | button |
  |---|---|---|---|---|---|
  | accent text `#3B2F86` (focus ring, selected toggle border) | 10.84 | 10.02 | 9.41 | 9.70 | 8.66 |
  | lavender-mid `#8E86D9` | 3.20 | **2.96** | **2.78** | **2.86** | **2.55** |
  | accent-ring `#B9B2EE` | **1.97** | **1.82** | **1.71** | **1.76** | **1.57** |
  | profit-strong `#2EA067` | 3.31 | 3.06 | — | **2.96** | — |
  | loss-strong `#E2665E` | 3.34 | 3.08 | — | **2.98** | — |

- **Focus ring**: `--ring` = accent text `#3B2F86`, always at full opacity (`ring-ring`,
  `outline-ring`, never `ring-ring/50`). lavender-mid and accent-ring fail 3:1 on page/chrome.
- **Selected toggle buttons** (filters, presets, choice chips): `selectedToggleClass` in `tones.ts` =
  accent-text border + button fill + semibold accent text. Unselected = `border-input`, hover =
  `bg-accent` only, so hover never looks selected. Keep `aria-pressed`.
- Form control borders use `--tj-input` (1.46:1 on white, visual cue only; the focus ring is the
  accessible state indicator). Checkboxes use lavender-mid (3.20:1 on white, the card surface).
- Known gap (M8-10b): the selected KPI rings (profit-mid / loss-mid / accent-ring) are below 3:1; the
  pressed state is also shown by the hint pill text. Revisit when Home is rebuilt.

## 4. Typography

Fonts are self-hosted from `@fontsource/*` (5.3.0, pinned), imported in `index.css`; the browser
downloads only the latin/cyrillic subsets it needs. Works offline.

| Role | Utility | Font | Size / weight | Notes |
|---|---|---|---|---|
| Page title | `type-page-title` | Manrope | 28px / 800 | letter-spacing -0.02em |
| Section title | `type-section-title` | Manrope | 20px / 800 | -0.01em; used by `SectionHeader` |
| Card title | `type-card-title` | Manrope | 17px / 800 | use `text-base` for 16px |
| Hero number | `type-hero` | Manrope | 64px / 800 | line-height 1, letter-spacing -0.045em |
| Symbols (GER40, EURUSD) | `type-symbol` | Manrope | size per place / 800 | |
| Body | default (`body`) | Inter | 14px / 400 | |
| Secondary | `text-xs`, `text-[13px]` | Inter | 12-13px / 400-600 | colour muted |
| Numbers, prices, P&L, R | `num` | JetBrains Mono | inherits / 500-600 | tabular digits; right-aligned in columns |
| Chart labels | `num text-[11px]`..`text-[13px]` | JetBrains Mono | 11-13px / 500-600 | colour muted, never faint |
| KPI value | `type-kpi` | JetBrains Mono | 26px / 600 | -0.02em |

Imported weights: Manrope 700/800; Inter 400/500/600; JetBrains Mono 500/600. Do not use other
weights (the browser would substitute the nearest one); in particular no `font-bold` on `num`/mono
text (no JetBrains Mono 700), use `font-semibold`.
Decision (M8-10a review): `h1`/`h2` default to Manrope; existing pages keep their own sizes and
`font-semibold` until M8-10c, which renders as Manrope 700 (imported for this). New «Студія» titles
use the `type-*` utilities (800).

## 5. Shape and motion

| Token | Value | Use |
|---|---|---|
| `rounded-card` | 20px | Cards (18-22px range; KPI cards use 18px) |
| `rounded-tile` | 14px | Tiles and inner boxes (10-16px range) |
| `rounded-xl` / `rounded-[10px]` | 14px / 10px | Buttons, segmented control |
| `rounded-full` | 999px | Pills, badges, dots |
| `--radius` | 10px | shadcn base radius (inputs, popovers) |
| `lift` utility | translateY(-3px) + `0 16px 32px -20px rgba(40,40,60,.35)`, 180 ms | Opt-in card hover |
| `live-pulse` utility | 1.8 s ease-out ring pulse | `LiveDot` for open positions |
| `shadow-soft` | `0 1px 3px rgba(40,40,60,.08)` | Active sidebar item |
| `shadow-segment` | `0 1px 3px rgba(40,40,60,.12)` | Selected segment |

All motion is off under `prefers-reduced-motion: reduce`: `lift` and `live-pulse` include the media
query; transitions in components use `motion-reduce:transition-none` / `motion-reduce:animate-none`.

## 6. Components (`frontend/src/components/studio`)

| Component | Props | Notes |
|---|---|---|
| `Card` | `as?: 'section' \| 'article' \| 'div'` (default `section`), `lift?: boolean`, `variant?: 'surface' \| 'hero'`, plus div props | 20px radius, white, hairline border, `p-5` |
| `Tile` | `tone?: Tone`, div props | 14px radius, tone wash |
| `Pill` | `tone?: Tone`, `size?: 'sm' \| 'md'`, `mono?: boolean`, `dot?: boolean`, span props | Soft bg + own text colour; `dot` adds a strong-shade status dot (decorative) |
| `HeaderChip` | as `Pill` without `size` | Medium pill for the page header (session, bias, quick links) |
| `SegmentedControl<T>` | `label`, `value`, `options: {value,label}[]`, `onChange`, `disabled?`, `className?` | `role="radiogroup"`, roving tab stop, Arrow keys / Home / End move and select; a `value` not in `options` checks nothing and the first option keeps the tab stop |
| `KpiCard` | `label`, `value` (formatted), `hint?`, `tone?: 'profit' \| 'loss' \| 'accent' \| 'neutral'`, `selected?`, `onClick?`, `sparkline?: ReactNode`, `className?` | With `onClick`: `<button aria-pressed>`, `lift` hover, selected 2px ring. Without: a static `<div>` (no pressed state, no lift). Tone sets wash and value colour |
| `SectionHeader` | `title`, `level?: 2 \| 3`, `id?`, `children?` (pills/LiveDot), `actions?` | Manrope 20px title; actions right-aligned |
| `LiveDot` | `label?`, `className?` | Pulsing profit-strong dot; decorative unless `label` is given (`role="img"`) |
| `Button` (`components/ui/button`) | shadcn variants | `default` = pastel primary (`#E7E3FA` / `#3B2F86`); `secondary` and `outline` = white with border; `destructive` = loss-soft / loss text; `ghost`; `link` = lavender text |

`Tone` = `'neutral' | 'profit' | 'loss' | 'accent' | 'peach'`. Class maps are in `tones.ts`, plus
`selectedToggleClass` for the selected state of pressed toggle buttons outside `SegmentedControl`.

App shell: sidebar 236px (`#EFEFEC`, TJ mark gradient, active item white + soft shadow, count badges
`Pill tone="loss"`); footer status bar on `#EFEFEC` with status dots in profit-strong / loss-strong
(warning dots in warning-strong).

## 7. Display formatter (`frontend/src/lib/displayFormat.ts`)

| Function | Overview | Exact |
|---|---|---|
| `formatUsd(value, mode, { signed? })` | whole dollars: `+1 241`, `−90`, `0` | `formatMoney` / `formatSignedMoney` (2 dp) |
| `formatPct(value, mode, { signed? })` | one decimal: `+2.1%`, `57.0%` | `formatPercent` (2 dp) |
| `formatR(value, mode)` | one decimal, always signed: `+1.3R`, `−1.0R` | `formatR` (2 dp) |
| `formatPrice(value, mode)` | by magnitude: >= 1000 -> 0 dp (`26 523`), >= 10 -> 2 dp (`155.23`), else 4 dp (`1.1091`) | `formatPrice` (trailing zeros dropped, >= 2 dp) |
| `formatLots(value)` | always exact (`formatVolume`) | same |

- `mode` is `'overview'` (Home, digests, cards, charts, badges) or `'exact'` (calculator, trade
  details, Describe, Journal table, exports). Existing screens are switched in M8-10b/c.
- Input: decimal strings from the API (`"1241.4900"`, optional leading `+`/`-`) or JS numbers.
  `null`, `undefined`, NaN/Infinity, exponent strings, `"1,5"`, `".5"` and other non-decimals show `—`.
- Rounding: half away from zero (`2.5 -> 3`, `-2.5 -> −3`), done on the digit string, never through
  float, so strings with more digits than a double holds round correctly. Numbers are first turned
  into their shortest round-trip string (`String(n)`); tiny exponent numbers (`1e-7`) use 20 fixed
  digits; numbers >= 1e21 show `—`.
- Signs come from the rounded value: `-0.4` USD shows `0`, no sign. Negatives always use U+2212 `−`;
  `+` only for signed values. Thousands use U+202F narrow no-break space. Prices never get `+`.
- Price magnitude is decided on the integer digits; when rounding crosses a step (`9.99996` ->
  `10.0000`) the value is re-rounded for the new step (`10.00`).
- Display only: the DB and every calculation keep exact decimals.

## 8. Adding a dark theme later

1. Add a block in `index.css` after `:root`:
   ```css
   .dark {
     color-scheme: dark;
     --tj-page: ...; --tj-chrome: ...; --tj-surface: ...; /* every --tj-* token */
   }
   ```
   Layers 2 and 3 need no change: the shadcn variables and Tailwind names point at `--tj-*`.
2. Re-measure the contrast table for the new set (text, muted, profit, loss, accent, warning on each
   background) and keep the same rules.
3. Put `class="dark"` on `<html>` (or toggle it from a setting) and switch `meta color-scheme` and
   the Sonner `theme` prop in `components/ui/sonner.tsx`.
4. `@custom-variant dark` is kept, so `dark:` utilities still work for one-off overrides.

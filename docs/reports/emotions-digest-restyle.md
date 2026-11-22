# Emotion lists and digest restyle (owner request 2026-11-22)

Branch `feat/emotion-options`, from main `298c235`. Tier L for emotions (migration), S for the digest charts.

## Built
- Table `journal_field_options` (migration `e7c41b9a2d60`, new empty table, no trade data touched).
- Settings «Емоції»: two independent lists; add, rename (label only), reorder, hide/show, delete if unused, synonyms.
- New defaults «тривога» (`anxiety`), «невпевненість» (`uncertainty`).
- Describe form, Journal filters (emotion filters are new), digest breakdowns and the AI catalogue read the current lists.
- Digest «Розподіл R»: six bins, compact and centered. «Година» and «День»: pastel P&L cells.

## Screenshots
`docs/reports/digest-restyle-before/` and `docs/reports/digest-restyle-after/` at 1280 and 1440 (fictitious data).

## Not verified
- No live AI call was made; the moved synonyms are covered by fixtures only.
- The migration has not been applied to the dev DB; it runs with a backup on the next app start from a checkout containing this code.

## Open for the owner
- Exactly −1 R is counted in `−1…0`, see DECISIONS 2026-11-22.

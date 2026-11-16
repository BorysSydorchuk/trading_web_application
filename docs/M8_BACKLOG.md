# M8 backlog — UX & Functional Improvements

Source: PM review 2026-11-16 (owner feedback from normal use). Only **M8-11** is authorized; every other item needs a separate PM go.
Order (owner/PM): M8-11 -> M8-09 -> M8-01 -> M8-02 + M8-03 -> M8-04..M8-08 (one taxonomy batch, one migration) -> M8-10 (after the owner picks a design direction).
Five real live-validation days transferred from M7: **0/5**.

> Owner wording, full behaviour and acceptance for M8-02, 03, 04, 06, 08 and 10 come from section 5 of the PM handoff (requested from Borys 2026-11-16). Fields marked «TBD (§5)» are not invented here.

| ID | Owner wording | Behaviour | Acceptance | Priority | Tier | Depends on | Status |
|----|---------------|-----------|------------|----------|------|------------|--------|
| M8-01 | TBD (§5); PM summary: exclude a trade from statistics | Excluded trade leaves strategy statistics (win rate, R, expectancy, breakdowns, digests, «Потрібен опис») but stays in all real-money/risk numbers (account P&L, balances, daily/weekly stops, 10 trades/week limit, risk rule checks). Reversible, mandatory reason, raw MT5 data never changed, survives re-sync. | TBD (§5) | 3rd | L (migration, statistics) | M8-09 | planned |
| M8-02 | TBD (§5) | TBD (§5) | TBD (§5) | 4th (with M8-03) | TBD | M8-01 | planned |
| M8-03 | TBD (§5) | TBD (§5) | TBD (§5) | 4th (with M8-02) | TBD | M8-01 | planned |
| M8-04 | TBD (§5) | Part of the taxonomy batch (one migration with M8-05..08). | TBD (§5) | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-05 | TBD (§5) | H1/H4 context fields. Migration: old "Flow H1 synced with H4 = yes" -> H1 context = Flow AND H4 context = Flow; "no"/empty -> new fields empty, legacy value kept visible read-only. | TBD (§5) | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-06 | TBD (§5) | Part of the taxonomy batch. | TBD (§5) | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-07 | TBD (§5) | FVG type per timeframe: separate multi-select for FVG H1 and for FVG H4, each shown only when that POI is selected. | TBD (§5) | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-08 | TBD (§5) | Part of the taxonomy batch. | TBD (§5) | 5th (batch) | L (batch) | M8-02/03 | planned |
| M8-09 | TBD (§5); PM summary: automatic exit reason | Primary source: MT5 deal reason (DEAL_REASON_SL / DEAL_REASON_TP / client/manual etc.) of the closing deal(s); price match vs initial SL/TP only as fallback with tick tolerance; never overwrite a reason the owner entered; partial closes handled explicitly. | TBD (§5) | 2nd | L (MT5 sync) | M8-11 | planned |
| M8-10 | TBD (§5); PM summary: design direction | After the owner picks a design direction. | TBD (§5) | last | TBD | owner design choice | planned |
| M8-11 | Footer floats mid-screen with blank area below (seen on «Головна» after switching pages) | Footer stays at the viewport bottom on every route; no blank area; no page-level horizontal scroll 1280–2560 px; long pages scroll only the content area; route change resets content scroll to top. | Playwright regression (all main pages, short/long content, resize): footer bottom == viewport bottom, no extra document height; owner check: 10 fast page switches, resize, zoom 90%/110%. | 1st | S | — | in review |

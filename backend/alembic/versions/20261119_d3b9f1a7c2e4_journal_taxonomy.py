"""Journal taxonomy (M8-04..M8-08): H1/H4 context, POI and FVG types, daily/weekly risk.

Adds to ``trades``: ``h1_context`` / ``h4_context`` (VARCHAR(50)), ``poi_types``,
``fvg_types_h1``, ``fvg_types_h4`` (VARCHAR(50)[], NULL when empty, never '{}') and the
«Інше» texts ``h1_context_other``, ``h4_context_other``, ``poi_types_other``,
``fvg_types_h1_other``, ``fvg_types_h4_other``, ``entry_model_other`` (TEXT).

Data (pure SQL; exactly mapped old values move and the old column is emptied, the rest stays
in the old column as a read-only legacy value; old columns are never dropped):
- setup_context ``yes`` -> h1 = h4 = ``flow``, setup_context NULL; ``no`` / ``partially`` kept;
- fvg_kind fractal_updating / post_manipulation with poi_type fvg_h1 / fvg_h4 -> fvg_types_h1 /
  fvg_types_h4 = [kind], fvg_kind NULL; otherwise kept (``na``, or the POI is not an FVG);
- poi_type X -> poi_types = [X], poi_type_other -> poi_types_other; both old columns NULL;
- rule_violations with daily_stop_loss_pct / daily_stop_profit_pct -> ``daily_risk``, the
  weekly ones -> ``weekly_risk``; details ``<old key>: <old details>`` (``<old key>`` when
  there were none); two rows of one trade merge into one (loss part first, joined by "; ",
  source user if either was user);
- journal_field_requirements: rows of setup_context / poi_type / fvg_kind deleted; rows for
  the new required keys (incl. fvg_types_h1 / fvg_types_h4) inserted with now() (ON CONFLICT
  DO NOTHING), only when the first fill already happened (initial_fill_at set): a fresh DB
  keeps the 1970 first-fill rule.

Downgrade restores the old columns where one value exists (poi_types[1]; h1 = h4 = flow ->
yes; the single FVG type of the POI -> fvg_kind), splits daily_risk / weekly_risk back by their
"; " parts and the old-key prefixes (a part without a known prefix goes to the loss key),
deletes the requirements rows of the new keys (the M3-07 sync re-stamps the old ones) and
drops the new columns. Extra multi values, other texts of H1/H4/FVG/entry model are lost.

Revision ID: d3b9f1a7c2e4
Revises: c6f2a8d4e173
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3b9f1a7c2e4"
down_revision: str | Sequence[str] | None = "c6f2a8d4e173"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPTION_COLUMNS = ("h1_context", "h4_context")
TEXT_COLUMNS = (
    "h1_context_other",
    "h4_context_other",
    "poi_types_other",
    "fvg_types_h1_other",
    "fvg_types_h4_other",
    "entry_model_other",
)
MULTI_COLUMNS = ("poi_types", "fvg_types_h1", "fvg_types_h4")
NEW_REQUIRED_KEYS = ("h1_context", "h4_context", "poi_types", "fvg_types_h1", "fvg_types_h4")
REMOVED_REQUIRED_KEYS = ("setup_context", "poi_type", "fvg_kind")

_MAP_CONTEXT = """
UPDATE trades SET h1_context = 'flow', h4_context = 'flow', setup_context = NULL
WHERE setup_context = 'yes'
"""
_MAP_FVG = """
UPDATE trades SET
  fvg_types_h1 = CASE WHEN poi_type = 'fvg_h1' THEN ARRAY[fvg_kind] END,
  fvg_types_h4 = CASE WHEN poi_type = 'fvg_h4' THEN ARRAY[fvg_kind] END,
  fvg_kind = NULL
WHERE fvg_kind IN ('fractal_updating', 'post_manipulation') AND poi_type IN ('fvg_h1', 'fvg_h4')
"""
_MAP_POI = """
UPDATE trades SET
  poi_types = CASE WHEN poi_type IS NOT NULL THEN ARRAY[poi_type] END,
  poi_types_other = poi_type_other,
  poi_type = NULL,
  poi_type_other = NULL
WHERE poi_type IS NOT NULL OR poi_type_other IS NOT NULL
"""
# A pre-existing daily_risk / weekly_risk row cannot exist before this revision (neither the
# engine nor the journal could write it); ON CONFLICT appends instead of losing a row anyway.
_MERGE_VIOLATIONS = """
WITH old AS (
  SELECT trade_id, rule_key, source, created_at,
    CASE WHEN rule_key LIKE 'daily%' THEN 'daily_risk' ELSE 'weekly_risk' END AS new_key,
    CASE WHEN rule_key LIKE '%loss_pct' THEN 0 ELSE 1 END AS part,
    CASE WHEN details IS NULL OR details = '' THEN rule_key
         ELSE rule_key || ': ' || details END AS part_details
  FROM rule_violations
  WHERE rule_key IN ('daily_stop_loss_pct', 'daily_stop_profit_pct',
                     'weekly_stop_loss_pct', 'weekly_stop_profit_pct')
)
INSERT INTO rule_violations (trade_id, rule_key, source, details, created_at)
SELECT trade_id, new_key,
  CASE WHEN bool_or(source = 'user') THEN 'user' ELSE 'auto' END,
  string_agg(part_details, '; ' ORDER BY part),
  min(created_at)
FROM old
GROUP BY trade_id, new_key
ON CONFLICT (trade_id, rule_key) DO UPDATE
  SET details = concat_ws('; ', rule_violations.details, EXCLUDED.details)
"""
_DELETE_OLD_VIOLATIONS = """
DELETE FROM rule_violations
WHERE rule_key IN ('daily_stop_loss_pct', 'daily_stop_profit_pct',
                   'weekly_stop_loss_pct', 'weekly_stop_profit_pct')
"""
_INSERT_REQUIREMENTS = """
INSERT INTO journal_field_requirements (key, required_since)
SELECT k, now() FROM unnest(CAST(:keys AS varchar[])) AS k
WHERE EXISTS (SELECT 1 FROM journal_requirements_state WHERE initial_fill_at IS NOT NULL)
ON CONFLICT (key) DO NOTHING
"""
_DELETE_REQUIREMENTS = "DELETE FROM journal_field_requirements WHERE key = ANY(:keys)"


def upgrade() -> None:
    for name in OPTION_COLUMNS:
        op.add_column("trades", sa.Column(name, sa.String(length=50), nullable=True))
    for name in TEXT_COLUMNS:
        op.add_column("trades", sa.Column(name, sa.Text(), nullable=True))
    for name in MULTI_COLUMNS:
        op.add_column(
            "trades", sa.Column(name, postgresql.ARRAY(sa.String(length=50)), nullable=True)
        )
    for sql in (_MAP_CONTEXT, _MAP_FVG, _MAP_POI, _MERGE_VIOLATIONS, _DELETE_OLD_VIOLATIONS):
        op.execute(sa.text(sql))
    op.execute(sa.text(_DELETE_REQUIREMENTS).bindparams(keys=list(REMOVED_REQUIRED_KEYS)))
    op.execute(sa.text(_INSERT_REQUIREMENTS).bindparams(keys=list(NEW_REQUIRED_KEYS)))


_SPLIT_VIOLATIONS = """
WITH parts AS (
  SELECT v.trade_id, v.source, v.created_at, p.ord, p.part,
    CASE WHEN v.rule_key = 'daily_risk' THEN 'daily' ELSE 'weekly' END AS period
  FROM rule_violations v
  CROSS JOIN LATERAL unnest(
    CASE WHEN v.details IS NULL OR v.details = '' THEN ARRAY['']
         ELSE string_to_array(v.details, '; ') END
  ) WITH ORDINALITY AS p(part, ord)
  WHERE v.rule_key IN ('daily_risk', 'weekly_risk')
), matched AS (
  SELECT *, regexp_match(part, '^(' || period || '_stop_(loss|profit)_pct)(?:: (.*))?$') AS m
  FROM parts
), keyed AS (
  SELECT trade_id, source, created_at, ord,
    COALESCE(m[1], period || '_stop_loss_pct') AS old_key,
    CASE WHEN m IS NULL THEN NULLIF(part, '') ELSE m[3] END AS old_details
  FROM matched
)
INSERT INTO rule_violations (trade_id, rule_key, source, details, created_at)
SELECT trade_id, old_key,
  CASE WHEN bool_or(source = 'user') THEN 'user' ELSE 'auto' END,
  string_agg(old_details, '; ' ORDER BY ord),
  min(created_at)
FROM keyed
GROUP BY trade_id, old_key
ON CONFLICT (trade_id, rule_key) DO NOTHING
"""
_DELETE_NEW_VIOLATIONS = (
    "DELETE FROM rule_violations WHERE rule_key IN ('daily_risk', 'weekly_risk')"
)
_RESTORE_CONTEXT = """
UPDATE trades SET setup_context = 'yes'
WHERE setup_context IS NULL AND h1_context = 'flow' AND h4_context = 'flow'
"""
_RESTORE_POI = """
UPDATE trades
SET poi_type = poi_types[1], poi_type_other = COALESCE(poi_type_other, poi_types_other)
WHERE poi_type IS NULL AND cardinality(poi_types) > 0
"""
# The single FVG type of the restored POI (or of the only FVG list) becomes fvg_kind.
_RESTORE_FVG = """
UPDATE trades SET fvg_kind = t.kind
FROM (
  SELECT id, CASE
    WHEN poi_type = 'fvg_h1' THEN CASE WHEN cardinality(fvg_types_h1) = 1 THEN fvg_types_h1[1] END
    WHEN poi_type = 'fvg_h4' THEN CASE WHEN cardinality(fvg_types_h4) = 1 THEN fvg_types_h4[1] END
    WHEN fvg_types_h4 IS NULL AND cardinality(fvg_types_h1) = 1 THEN fvg_types_h1[1]
    WHEN fvg_types_h1 IS NULL AND cardinality(fvg_types_h4) = 1 THEN fvg_types_h4[1]
  END AS kind
  FROM trades WHERE fvg_kind IS NULL
) AS t
WHERE trades.id = t.id AND t.kind IN ('fractal_updating', 'post_manipulation')
"""


def downgrade() -> None:
    for sql in (
        _SPLIT_VIOLATIONS,
        _DELETE_NEW_VIOLATIONS,
        _RESTORE_CONTEXT,
        _RESTORE_POI,
        _RESTORE_FVG,
    ):
        op.execute(sa.text(sql))
    op.execute(sa.text(_DELETE_REQUIREMENTS).bindparams(keys=list(NEW_REQUIRED_KEYS)))
    for name in (*MULTI_COLUMNS, *TEXT_COLUMNS, *OPTION_COLUMNS):
        op.drop_column("trades", name)

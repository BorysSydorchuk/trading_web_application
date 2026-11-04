"""`journal_field_requirements` kept in sync with config/journal_fields.yaml, and the SQL
form of `missing_new_fields` for the trades list (docs/api.md M3 "New required fields").

Sync rule: a field required now without a row gets one, a row of a field no longer
required is deleted. The very first sync in the life of the DB (marker row
`journal_requirements_state.initial_fill_at` still NULL) stamps 1970-01-01 (the field
applies to every trade); every later addition gets "now" (UTC).

Called on every journal read/save/extraction and by a worker job, from two processes:
- no write when the table already matches the YAML (one SELECT per call);
- a write takes `FOR UPDATE` on the marker row first, so concurrent syncs are serialised
  and the first fill happens exactly once; inserts are ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import (
    ColumnElement,
    String,
    Text,
    and_,
    delete,
    exists,
    false,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config_files.journal_fields import JournalFieldsConfig
from app.domain.journal import RULE_VIOLATIONS_KEY, JournalKey, journal_keys, required_field_keys
from app.models import ChartLink, RuleViolation, Trade
from app.models.enums import ChartLinkKind
from app.models.journal_requirement import (
    STATE_ROW_ID,
    JournalFieldRequirement,
    JournalRequirementsState,
)
from app.services.trade_journal import OVERRIDE_SUFFIX

logger = logging.getLogger(__name__)

# required_since of the fields required when the table is filled for the first time.
INITIAL_REQUIRED_SINCE = datetime(1970, 1, 1, tzinfo=UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def load_requirements(db: Session) -> dict[str, datetime]:
    rows = db.execute(select(JournalFieldRequirement.key, JournalFieldRequirement.required_since))
    return {row.key: row.required_since for row in rows}


def _lock_state(db: Session, now: datetime) -> JournalRequirementsState:
    """The marker row, locked until commit. Recreated (as "already filled") if missing."""
    query = (
        select(JournalRequirementsState)
        .where(JournalRequirementsState.id == STATE_ROW_ID)
        .with_for_update()
    )
    state = db.scalars(query).one_or_none()
    if state is None:
        logger.warning("journal_requirements_state row missing; recreated as already filled")
        db.execute(
            pg_insert(JournalRequirementsState)
            .values(id=STATE_ROW_ID, initial_fill_at=now)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        state = db.scalars(query).one()
    return state


def _write(db: Session, wanted: tuple[str, ...], now: datetime) -> None:
    state = _lock_state(db, now)
    current = load_requirements(db)  # re-read under the lock: another process may have synced
    if set(current) == set(wanted):
        return
    first_fill = state.initial_fill_at is None
    if first_fill:
        state.initial_fill_at = now
    since = INITIAL_REQUIRED_SINCE if first_fill else now
    removed = sorted(set(current) - set(wanted))
    added = [key for key in wanted if key not in current]
    if removed:
        db.execute(delete(JournalFieldRequirement).where(JournalFieldRequirement.key.in_(removed)))
    if added:
        db.execute(
            pg_insert(JournalFieldRequirement)
            .values([{"key": key, "required_since": since} for key in added])
            .on_conflict_do_nothing(index_elements=["key"])
        )
    logger.info(
        "Journal requirements synced%s: added %s (required since %s), removed %s",
        " (first fill)" if first_fill else "",
        added or "-",
        since.isoformat(),
        removed or "-",
    )


def sync_requirements(
    db: Session, config: JournalFieldsConfig, now: Callable[[], datetime] = _utc_now
) -> dict[str, datetime]:
    """Bring the table in line with `config` (commits only when it wrote) and return
    {key: required_since} for the fields required now. Call it before other work in the
    session: a write commits the session's transaction."""
    wanted = required_field_keys(config)
    current = load_requirements(db)
    if set(current) == set(wanted):
        return current
    try:
        _write(db, wanted, now())
        db.commit()
    except Exception:
        db.rollback()
        raise
    return load_requirements(db)


# --- SQL form of missing_new_fields (GET /api/trades?missing_new_fields=true) ---


def _empty_json(value: ColumnElement[object]) -> ColumnElement[bool]:
    """Same as the Python `_is_empty` for a JSONB value: missing, null, "" or []."""
    return or_(
        value.is_(None),
        func.jsonb_typeof(value) == "null",
        value == literal("", JSONB),
        value == literal([], JSONB),
    )


def _empty_sql(spec: JournalKey) -> ColumnElement[bool]:
    """ "Empty on this trade" for one required field, per storage (mirrors stored_journal)."""
    if spec.type == "links":
        before = select(ChartLink.id).where(
            ChartLink.trade_id == Trade.id, ChartLink.kind == ChartLinkKind.BEFORE.value
        )
        return ~exists(before)
    if spec.key == RULE_VIOLATIONS_KEY and spec.is_relation:
        return ~exists(select(RuleViolation.id).where(RuleViolation.trade_id == Trade.id))
    if spec.storage == "extra":
        return _empty_json(Trade.extra[spec.key])
    column = Trade.__table__.c[spec.key]
    if spec.type == "auto":
        override = Trade.__table__.c.get(spec.key + OVERRIDE_SUFFIX)
        if override is not None:
            return func.coalesce(override, column).is_(None)
    if isinstance(column.type, JSONB):
        return _empty_json(column)
    if isinstance(column.type, String | Text):
        return or_(column.is_(None), column == "")
    return column.is_(None)


def missing_new_fields_condition(
    config: JournalFieldsConfig, required_since: Mapping[str, datetime]
) -> ColumnElement[bool]:
    """Closed trades with a non-empty `missing_new_fields` (same rule as
    `app.domain.journal.missing_new_fields`)."""
    per_field = [
        and_(Trade.close_time < required_since[spec.key], _empty_sql(spec))
        for spec in journal_keys(config)
        if not spec.is_text_key and spec.field.required and spec.key in required_since
    ]
    if not per_field:
        return false()
    return and_(Trade.close_time.is_not(None), or_(*per_field))

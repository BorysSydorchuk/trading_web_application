"""One trade's journal: the read view (TradeDetail.journal) and the save
(PUT /api/trades/{id}/journal), both driven by config/journal_fields.yaml (docs/api.md M2).

Field logic (keys, types, completeness) is in `app.domain.journal`; this module maps it to
the Trade row: columns vs `trades.extra`, user rule violations and chart links.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files.journal_fields import JournalFieldsConfig
from app.domain.chart_links import duplicate_link_indexes, preview_url
from app.domain.journal import (
    RULE_VIOLATIONS_KEY,
    JournalKey,
    filter_ai_filled,
    journal_keys,
    merge_extra,
    missing_required,
    split_storage,
    validate_fields,
    visible_journal,
    writable_keys,
)
from app.errors import ApiError
from app.models import ChartLink, RuleViolation, Trade
from app.models.enums import ChartLinkKind, TradeStatus, ViolationSource
from app.schemas.trades import JournalInput
from app.services.trade_rules import recompute_rules_for_trade

logger = logging.getLogger(__name__)

# Suffix of the column holding the user's override of an `auto` field (bias_alignment).
OVERRIDE_SUFFIX = "_override"


@dataclass(frozen=True)
class JournalView:
    journal: dict[str, Any]
    chart_links: list[dict[str, Any]]
    missing_required: list[str]


def _stored_value(trade: Trade, spec: JournalKey) -> Any:
    if spec.type == "links":
        return None
    if spec.key == RULE_VIOLATIONS_KEY and spec.is_relation:
        return sorted(v.rule_key for v in trade.rule_violations)
    if spec.storage == "extra":
        return trade.extra.get(spec.key)
    value = getattr(trade, spec.key, None)
    if spec.type == "auto":
        override = getattr(trade, spec.key + OVERRIDE_SUFFIX, None)
        return override if override is not None else value
    return value


def stored_journal(trade: Trade, config: JournalFieldsConfig) -> dict[str, Any]:
    """Raw stored value of every YAML key (needs rule_violations loaded)."""
    return {spec.key: _stored_value(trade, spec) for spec in journal_keys(config)}


def _has_before_link(kinds: Sequence[str]) -> bool:
    return ChartLinkKind.BEFORE.value in kinds


def journal_view(trade: Trade, config: JournalFieldsConfig) -> JournalView:
    """journal, chart_links and missing_required of TradeDetail (needs relations loaded)."""
    stored = stored_journal(trade, config)
    links = sorted(trade.chart_links, key=lambda link: link.id)
    return JournalView(
        journal=visible_journal(config, stored),
        chart_links=[
            {"id": c.id, "url": c.url, "kind": c.kind, "preview_url": preview_url(c.url)}
            for c in links
        ],
        missing_required=missing_required(
            config, stored, has_before_link=_has_before_link([c.kind for c in links])
        ),
    )


# --- save ---


def _check_status(trade: Trade) -> None:
    if trade.status == TradeStatus.OPEN.value or trade.close_time is None:
        raise ApiError(409, "trade_open", "An open trade cannot be described yet", {"id": trade.id})
    if trade.status == TradeStatus.NEEDS_SL.value:
        raise ApiError(409, "needs_sl", "Set the initial SL before the journal", {"id": trade.id})


def _input_errors(
    data: JournalInput, config: JournalFieldsConfig, trade: Trade
) -> tuple[dict[str, Any], dict[str, str]]:
    result = validate_fields(config, data.fields, stored_journal(trade, config))
    errors = {f"fields.{key}": issue.message for key, issue in result.errors.items()}
    for i in duplicate_link_indexes([link.url for link in data.chart_links]):
        errors[f"chart_links.{i}.url"] = "duplicate link (same snapshot or chart)"
    return result.values, errors


def _apply_values(trade: Trade, config: JournalFieldsConfig, values: dict[str, Any]) -> None:
    columns, extra = split_storage(config, values)
    for key, value in columns.items():
        setattr(trade, key, value)
    trade.extra = merge_extra(config, trade.extra, extra)


def _save_violations(
    db: Session, trade: Trade, config: JournalFieldsConfig, values: dict[str, Any]
) -> None:
    """User rows follow the confirmed list; auto rows are only changed by the recompute.

    "Auto" means auto rows at request time (what the UI showed as locked): a listed key
    that was auto never becomes a user row, even if the recompute now drops it.
    Order: drop user rows not in the list, recompute auto rows (journal values such as
    entry_model feed the rules), then add user rows for listed non-auto keys without a row.
    """
    managed = any(k.key == RULE_VIOLATIONS_KEY for k in writable_keys(config))
    wanted = set(values.get(RULE_VIOLATIONS_KEY) or ()) if managed else set()
    rows = db.scalars(select(RuleViolation).where(RuleViolation.trade_id == trade.id)).all()
    auto_before = {r.rule_key for r in rows if r.source == ViolationSource.AUTO.value}
    wanted_user = wanted - auto_before
    if managed:
        for row in rows:
            if row.source == ViolationSource.USER.value and row.rule_key not in wanted:
                db.delete(row)
    db.flush()
    recompute_rules_for_trade(db, trade, "journal save")
    present = set(
        db.scalars(select(RuleViolation.rule_key).where(RuleViolation.trade_id == trade.id))
    )
    for rule_key in sorted(wanted_user - present):
        db.add(
            RuleViolation(trade_id=trade.id, rule_key=rule_key, source=ViolationSource.USER.value)
        )
    db.flush()
    db.expire(trade, ["rule_violations"])


def save_journal(
    db: Session, trade: Trade, data: JournalInput, config: JournalFieldsConfig, now: datetime
) -> None:
    """Apply a JournalInput (full replacement). Flushes, never commits.

    Raises ApiError: 409 trade_open / needs_sl, 422 validation_error, 422
    journal_incomplete (the session is rolled back: nothing is saved).
    """
    _check_status(trade)
    values, errors = _input_errors(data, config, trade)
    if errors:
        raise ApiError(422, "validation_error", "Request validation failed", {"fields": errors})
    old_status = trade.status
    _apply_values(trade, config, values)
    trade.raw_text = data.raw_text
    trade.ai_filled_fields = filter_ai_filled(data.ai_filled_fields, values)
    trade.chart_links = [ChartLink(url=link.url, kind=link.kind) for link in data.chart_links]
    _save_violations(db, trade, config, values)
    trade.status = (TradeStatus.COMPLETE if data.complete else TradeStatus.DRAFT).value
    trade.described_at = now
    if data.complete:
        has_before = _has_before_link([link.kind for link in data.chart_links])
        missing = missing_required(
            config, stored_journal(trade, config), has_before_link=has_before
        )
        if missing:
            trade_id = trade.id
            db.rollback()
            logger.info("Trade %s: journal not saved, incomplete: %s", trade_id, missing)
            raise ApiError(
                422,
                "journal_incomplete",
                "Required journal fields are missing",
                {"missing": missing},
            )
    db.flush()
    logger.info("Trade %s: journal saved, status %s -> %s", trade.id, old_status, trade.status)

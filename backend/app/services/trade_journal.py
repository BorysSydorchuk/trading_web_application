"""One trade's journal: the read view (TradeDetail.journal) and the save
(PUT /api/trades/{id}/journal), both driven by config/journal_fields.yaml (docs/api.md M2).

Field logic (keys, types, completeness) is in `app.domain.journal`; this module maps it to
the Trade row: columns vs `trades.extra`, user rule violations and chart links.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config_files.journal_fields import JournalFieldsConfig
from app.domain.chart_links import duplicate_link_indexes, preview_url
from app.domain.exit_reason import source_after_owner_save
from app.domain.journal import (
    RULE_VIOLATIONS_KEY,
    JournalKey,
    RequirementScope,
    filter_ai_filled,
    journal_keys,
    merge_extra,
    missing_new_fields,
    missing_required,
    split_storage,
    validate_fields,
    visible_journal,
    writable_keys,
)
from app.errors import ApiError
from app.models import ChartLink, RuleViolation, Trade
from app.models.enums import ChartLinkKind, TradeStatus, ViolationSource
from app.schemas.trades import ChartLinkIn, JournalInput
from app.services.trade_rules import recompute_rules_for_trade

logger = logging.getLogger(__name__)

# Suffix of the column holding the user's override of an `auto` field (bias_alignment).
OVERRIDE_SUFFIX = "_override"


@dataclass(frozen=True)
class JournalView:
    journal: dict[str, Any]
    chart_links: list[dict[str, Any]]
    missing_required: list[str]
    missing_new_fields: list[str]


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


def requirement_scope(trade: Trade, required_since: Mapping[str, datetime]) -> RequirementScope:
    return RequirementScope(required_since=required_since, close_time=trade.close_time)


def journal_view(
    trade: Trade, config: JournalFieldsConfig, required_since: Mapping[str, datetime]
) -> JournalView:
    """journal, chart_links, missing_required and missing_new_fields of TradeDetail (needs
    relations loaded). `required_since` = synced `journal_field_requirements`."""
    stored = stored_journal(trade, config)
    links = sorted(trade.chart_links, key=lambda link: link.id)
    has_before = _has_before_link([c.kind for c in links])
    scope = requirement_scope(trade, required_since)
    journal = visible_journal(config, stored)
    config = journal_config_for(trade, config)  # missing lists: pre-entry only while open
    return JournalView(
        journal=journal,
        chart_links=[
            {"id": c.id, "url": c.url, "kind": c.kind, "preview_url": preview_url(c.url)}
            for c in links
        ],
        missing_required=missing_required(config, stored, has_before_link=has_before, scope=scope),
        missing_new_fields=missing_new_fields(
            config, stored, has_before_link=has_before, scope=scope
        ),
    )


# --- save ---


def is_open(trade: Trade) -> bool:
    """The one rule for "position still open" (status open, no close time)."""
    return trade.status == TradeStatus.OPEN.value or trade.close_time is None


def journal_config_for(trade: Trade, config: JournalFieldsConfig) -> JournalFieldsConfig:
    """An open position carries only the pre-entry fields (M8-02); a closed trade all."""
    return config.for_open_trade() if is_open(trade) else config


def check_describable(trade: Trade) -> None:
    """409 needs_sl: a closed trade needs its initial SL before the journal (and AI).

    An open trade may be described (M8-02): pre-entry fields only, see `save_journal`.
    """
    if trade.status == TradeStatus.NEEDS_SL.value:
        raise ApiError(409, "needs_sl", "Set the initial SL before the journal", {"id": trade.id})


def _input_errors(
    data: JournalInput, config: JournalFieldsConfig, trade: Trade
) -> tuple[dict[str, Any], dict[str, str]]:
    result = validate_fields(config, data.fields, stored_journal(trade, config))
    errors = {f"fields.{key}": issue.message for key, issue in result.errors.items()}
    for i in duplicate_link_indexes([link.url for link in data.chart_links]):
        errors[f"chart_links.{i}.url"] = "duplicate link (same snapshot or chart)"
    if is_open(trade):
        errors |= _open_trade_errors(data, config, result.values)
    return result.values, errors


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == ()


def _open_trade_errors(
    data: JournalInput, config: JournalFieldsConfig, values: Mapping[str, Any]
) -> dict[str, str]:
    """After-trade fields and «після угоди» links wait for the close (M8-02)."""
    errors: dict[str, str] = {}
    for spec in config.after_fields():
        for key in (spec.key, spec.text_key):
            if key is not None and not _is_empty(values.get(key)):
                errors[f"fields.{key}"] = "after-trade field: fill it in after the close"
    for i, link in enumerate(data.chart_links):
        if link.kind == ChartLinkKind.AFTER.value:
            errors[f"chart_links.{i}.kind"] = "after-trade link: add it after the close"
    return errors


def keep_after_trade(data: JournalInput, config: JournalFieldsConfig, trade: Trade) -> JournalInput:
    """A form built while the trade was open, saved after the close (M8-02): it never had the
    after-trade fields or «після угоди» links, so the stored ones (e.g. the M8-09 exit-reason
    prefill) are kept instead of being cleared by the full replacement."""
    stored = stored_journal(trade, config)
    after_keys = {key for spec in config.after_fields() for key in (spec.key, spec.text_key) if key}
    fields = {k: v for k, v in data.fields.items() if k not in after_keys}
    fields |= {key: stored.get(key) for key in after_keys}
    links = [link for link in data.chart_links if link.kind != ChartLinkKind.AFTER.value]
    links += [
        ChartLinkIn(url=c.url, kind=ChartLinkKind.AFTER.value)
        for c in sorted(trade.chart_links, key=lambda link: link.id)
        if c.kind == ChartLinkKind.AFTER.value
    ]
    ai_filled = [k for k in data.ai_filled_fields if k not in after_keys]
    ai_filled += [k for k in trade.ai_filled_fields if k in after_keys]
    return data.model_copy(
        update={"fields": fields, "chart_links": links, "ai_filled_fields": ai_filled}
    )


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
    db: Session,
    trade: Trade,
    data: JournalInput,
    config: JournalFieldsConfig,
    now: datetime,
    required_since: Mapping[str, datetime],
) -> None:
    """Apply a JournalInput (full replacement). Flushes, never commits.

    `complete: true` needs only the required fields that apply to the trade (closed at or
    after their `required_since`); a field made required later never blocks it.

    Raises ApiError: 409 needs_sl / open_trade_complete, 422 validation_error, 422
    journal_incomplete (the session is rolled back: nothing is saved).
    """
    check_describable(trade)
    open_trade = is_open(trade)
    if data.form_open and not open_trade:
        data = keep_after_trade(data, config, trade)
    if open_trade and data.complete:
        raise ApiError(
            409, "open_trade_complete", "An open trade cannot be completed", {"id": trade.id}
        )
    values, errors = _input_errors(data, config, trade)
    if errors:
        raise ApiError(422, "validation_error", "Request validation failed", {"fields": errors})
    old_status = trade.status
    old_exit_reason = trade.exit_reason
    _apply_values(trade, config, values)
    # M8-09: a changed or cleared exit reason is the owner's; the sync never touches it again.
    trade.exit_reason_source = source_after_owner_save(
        old_exit_reason, trade.exit_reason, trade.exit_reason_source
    )
    trade.raw_text = data.raw_text
    trade.ai_filled_fields = filter_ai_filled(data.ai_filled_fields, values)
    trade.chart_links = [ChartLink(url=link.url, kind=link.kind) for link in data.chart_links]
    _save_violations(db, trade, config, values)
    if not open_trade:  # an open trade stays open; the close makes it a draft (next_status)
        trade.status = (TradeStatus.COMPLETE if data.complete else TradeStatus.DRAFT).value
    trade.described_at = now
    if data.complete:
        has_before = _has_before_link([link.kind for link in data.chart_links])
        missing = missing_required(
            config,
            stored_journal(trade, config),
            has_before_link=has_before,
            scope=requirement_scope(trade, required_since),
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

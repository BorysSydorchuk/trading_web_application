"""Seed the M6 QA database from ``digest_qa.json`` through the real sync (M6-08).

    (backend/)  uv run python -m tests.fixtures.mt5.digest_qa_seed

Run by ``scripts/qa_live_check_m6.py --seed`` with DATABASE_URL = the local
``trading_journal_qa_m6`` and CONFIG_DIR = the QA config copy. Refuses any other database and a
database that already has accounts (seeds once, never changes or deletes existing rows).
For each account it inserts the account row (like POST /api/accounts) and runs
``app.services.sync.sync_account`` with a `FixtureMt5Source` at the fixture's sync instants
(pass 1 = step 0, pass 2 = step 1). Bias notes, journal values and the archive of account C
go through the HTTP API afterwards (the launcher). SYNTHETIC data only, no MT5, no network.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.config_files import get_rules
from app.config_files.symbols import get_symbols_config
from app.db import make_engine, make_session_factory
from app.models import Account
from app.mt5.fixture import FixtureMt5Source
from app.services.sync import sync_account

QA_DB_NAME = "trading_journal_qa_m6"
FIXTURE = Path(__file__).resolve().parent / "digest_qa.json"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
QA_PASSWORD = SecretStr("qa")  # the fixture only checks that a password is present


class SeedError(Exception):
    """A fixed, readable reason; never contains the database URL."""


def check_target(url: str) -> None:
    try:
        parts = urlsplit(url)
        ok = (
            parts.scheme == "postgresql+psycopg"
            and parts.hostname in LOCAL_HOSTS
            and parts.path == "/" + QA_DB_NAME
            and not parts.query
            and not parts.fragment
        )
        port = parts.port
    except ValueError:
        ok, port = False, None
    if not ok or (port is not None and not 1 <= port <= 65535):
        raise SeedError("refused: not the local QA database " + QA_DB_NAME)


def load_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != "digest_qa/1" or "SYNTHETIC" not in data.get("description", ""):
        raise SeedError("refused: not the SYNTHETIC digest_qa/1 fixture")
    return data


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _new_account(spec: Mapping[str, Any]) -> Account:
    size = Decimal(spec["size"])
    return Account(
        name=spec["name"],
        firm=spec["firm"],
        program=spec["program"],
        phase=spec["phase"],
        login=int(spec["login"]),
        server=spec["server"],
        terminal_path=None,
        starting_balance=size,
        currency=spec["currency"],
        status="active",
        reference_balance=size,
    )


def seed(factory: sessionmaker[Session], data: Mapping[str, Any]) -> list[str]:
    """Insert the accounts and sync them pass by pass; one line per sync for the console."""
    rules = get_rules()
    symbols = get_symbols_config()
    with factory() as session:
        if session.scalar(select(func.count()).select_from(Account)):
            raise SeedError("refused: the QA database already has accounts (seeded before)")
        ids: dict[str, int] = {}
        for spec in data["accounts"]:
            row = _new_account(spec)
            session.add(row)
            session.flush()
            ids[spec["key"]] = row.id
        session.commit()
    lines: list[str] = []
    for index, instant in enumerate(data["sync_passes"]):
        now = _utc(instant)
        for spec in data["accounts"]:
            if index < int(spec["first_pass"]):
                continue
            source = FixtureMt5Source(spec["fixture"], step=index)
            with factory() as session:
                stored = session.get(Account, ids[spec["key"]])
                if stored is None:
                    raise SeedError("refused: a seeded account disappeared")
                log = sync_account(
                    session,
                    stored,
                    source,
                    rules,
                    now,
                    password_for=lambda _login: QA_PASSWORD,
                    symbols=symbols,
                )
                lines.append(
                    f"pass {index + 1} account {spec['key']}: ok={log.ok} "
                    f"created={log.trades_created} updated={log.trades_updated} "
                    f"open={log.open_positions} error={log.error_code}"
                )
                if not log.ok:
                    raise SeedError(f"sync failed for account {spec['key']}: {log.error_code}")
    return lines


def main() -> int:
    try:
        url = get_settings().database_url
        check_target(url)
        data = load_fixture()
        engine = make_engine(url)
        try:
            for line in seed(make_session_factory(engine), data):
                print("[seed] " + line, flush=True)
        finally:
            engine.dispose()
    except SeedError as exc:
        print("[seed] " + str(exc), flush=True)
        return 2
    print("[seed] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

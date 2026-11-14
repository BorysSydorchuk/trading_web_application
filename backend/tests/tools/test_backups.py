"""M7-01 contract: fake dumps, no database or external tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services import backups as b

URL = "postgresql+psycopg://journal:fake-secret@127.0.0.1:5432/synthetic_test"
NOW = datetime(2026, 11, 14, 18, tzinfo=UTC)


def dump(url: str, path: Path) -> None:
    path.write_bytes(b"PGDMP synthetic")


def verify(path: Path) -> None:
    assert path.read_bytes().startswith(b"PGDMP")


def service(root: Path) -> b.BackupStore:
    return b.BackupStore(root, dump=dump, verify=verify)


def test_verified_atomic_publication_and_no_secret_metadata(tmp_path: Path) -> None:
    store = service(tmp_path)
    item = store.create(URL, now=NOW)
    assert item.archive.read_bytes() == b"PGDMP synthetic"
    assert store.verified(URL) == [item]
    metadata = (item.directory / "manifest.json").read_text(encoding="utf-8")
    assert "fake-secret" not in metadata
    assert "journal" not in metadata
    assert not list(tmp_path.rglob("*.partial"))


@pytest.mark.parametrize("stage", ["dump", "verify"])
def test_failure_never_publishes_or_prunes(tmp_path: Path, stage: str) -> None:
    store = service(tmp_path)
    old = store.create(URL, now=NOW)

    def fail(*args: object) -> None:
        raise OSError("fake-secret MUST NOT LEAK")

    broken = b.BackupStore(tmp_path, dump=fail if stage == "dump" else dump,
                           verify=fail if stage == "verify" else verify)
    with pytest.raises(b.BackupFailure) as exc:
        broken.create(URL, now=NOW + timedelta(days=1))
    assert "fake-secret" not in str(exc.value)
    assert store.verified(URL) == [old]


def test_checksum_corruption_refuses_retention(tmp_path: Path) -> None:
    store = service(tmp_path)
    old = store.create(URL, now=NOW)
    old.archive.write_bytes(b"corrupt")
    with pytest.raises(b.BackupFailure):
        store.prune(URL)
    assert old.archive.exists()


def test_retention_union_scopes_and_manual_protection(tmp_path: Path) -> None:
    store = service(tmp_path)
    items = [store.create(URL, now=NOW - timedelta(days=i)) for i in range(220)]
    manual = store.create(URL, kind="manual", now=NOW - timedelta(days=500))
    pre = store.create(URL, kind="pre-migration", now=NOW - timedelta(days=500))
    other = store.create(URL.replace("synthetic_test", "other_test"), now=NOW)
    keep = b.retention_union(items)
    deleted = store.prune(URL)
    assert {x.directory for x in store.verified(URL)} == keep
    assert len(deleted) == len(items) - len(keep)
    assert items[0].archive.exists()
    assert manual.archive.exists() and pre.archive.exists() and other.archive.exists()
    assert len(keep) >= 14
    assert len(keep) <= 28


def test_brussels_day_week_month_and_latest_representative(tmp_path: Path) -> None:
    store = service(tmp_path)
    # UTC Sunday becomes Brussels Monday, and UTC Jan 31 becomes February.
    dates = [datetime(2026, 1, 31, 23, 30, tzinfo=UTC),
             datetime(2026, 2, 1, 23, 30, tzinfo=UTC),
             datetime(2026, 2, 2, 12, tzinfo=UTC)]
    items = [store.create(URL, now=date) for date in dates]
    assert b.retention_union(items, daily=0, weekly=1, monthly=1) == {items[2].directory}
    assert b.retention_union(items, daily=0, weekly=0, monthly=0) == {items[2].directory}


def test_duplicate_timestamp_does_not_overwrite(tmp_path: Path) -> None:
    store = service(tmp_path)
    first = store.create(URL, now=NOW)
    second = store.create(URL, now=NOW)
    assert first.directory != second.directory
    assert first.archive.exists() and second.archive.exists()


@pytest.mark.parametrize("url", ["sqlite:///x", "postgresql://u:p@host/", "broken"])
def test_invalid_targets_refused_before_dump(tmp_path: Path, url: str) -> None:
    with pytest.raises(b.BackupFailure):
        service(tmp_path).create(url, now=NOW)
    assert list(tmp_path.iterdir()) == []


def test_lock_refuses_overlap_without_deleting_foreign_lock(tmp_path: Path) -> None:
    store = service(tmp_path)
    store.create(URL, now=NOW)
    scope = store.scope(URL)
    lock = scope / ".lock"
    lock.write_text("foreign", encoding="utf-8")
    with pytest.raises(b.BackupFailure):
        store.create(URL, now=NOW)
    assert lock.read_text(encoding="utf-8") == "foreign"


def test_unknown_files_and_manifest_extra_fields_fail_closed(tmp_path: Path) -> None:
    store = service(tmp_path)
    item = store.create(URL, now=NOW)
    unknown = item.directory / "owner-note.txt"
    unknown.write_text("keep", encoding="utf-8")
    with pytest.raises(b.BackupFailure):
        store.prune(URL)
    assert unknown.exists()
    unknown.unlink()
    manifest = item.directory / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["password"] = "not allowed"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(b.BackupFailure):
        store.prune(URL)
    assert item.archive.exists()

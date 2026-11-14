"""M7-01 contract: fake dumps, no database or external tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services import backups as b
from app.tools.migrate import parse_target

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

    broken = b.BackupStore(
        tmp_path,
        dump=fail if stage == "dump" else dump,
        verify=fail if stage == "verify" else verify,
    )
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
    assert manual.archive.exists()
    assert pre.archive.exists()
    assert other.archive.exists()
    assert len(keep) >= 14
    assert len(keep) <= 28


def test_brussels_day_week_month_and_latest_representative(tmp_path: Path) -> None:
    store = service(tmp_path)
    # UTC Sunday becomes Brussels Monday, and UTC Jan 31 becomes February.
    dates = [
        datetime(2026, 1, 31, 23, 30, tzinfo=UTC),
        datetime(2026, 2, 1, 23, 30, tzinfo=UTC),
        datetime(2026, 2, 2, 12, tzinfo=UTC),
    ]
    items = [store.create(URL, now=date) for date in dates]
    assert b.retention_union(items, daily=0, weekly=1, monthly=1) == {items[2].directory}
    assert b.retention_union(items, daily=0, weekly=0, monthly=0) == {items[2].directory}


def test_duplicate_timestamp_does_not_overwrite(tmp_path: Path) -> None:
    store = service(tmp_path)
    first = store.create(URL, now=NOW)
    second = store.create(URL, now=NOW)
    assert first.directory != second.directory
    assert first.archive.exists()
    assert second.archive.exists()


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
    data["password"] = "not allowed"  # noqa: S105 - invalid synthetic metadata
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(b.BackupFailure):
        store.prune(URL)
    assert item.archive.exists()


def test_archive_invisible_until_verification(tmp_path: Path) -> None:
    def inspect(path: Path) -> None:
        assert path.parent.name.endswith(".partial")
        assert not list(path.parent.parent.glob("*/manifest.json"))

    b.BackupStore(tmp_path, dump=dump, verify=inspect).create(URL, now=NOW)


def test_latest_daily_weekly_monthly_union_independent_expected(tmp_path: Path) -> None:
    store = service(tmp_path)
    dates = [
        datetime(2026, month, day, 18, tzinfo=UTC) for month in range(1, 12) for day in (1, 15, 28)
    ]
    items = [store.create(URL, now=day) for day in dates]
    # With no daily/weekly slots, latest six month-end representatives remain.
    expected = {items[index].directory for index in (17, 20, 23, 26, 29, 32)}
    assert b.retention_union(items, daily=0, weekly=0, monthly=6) == expected
    assert b.retention_union(items[-3:], daily=2, weekly=0, monthly=0) == {
        items[-1].directory,
        items[-2].directory,
    }


def test_credential_change_same_scope_other_host_isolated(tmp_path: Path) -> None:
    store = service(tmp_path)
    assert store.scope(URL) == store.scope(URL.replace("fake-secret", "new-secret"))
    assert store.scope(URL) != store.scope(URL.replace("127.0.0.1", "remote.example"))


def test_invalid_kind_and_naive_clock_do_not_touch_disk(tmp_path: Path) -> None:
    with pytest.raises(b.BackupFailure):
        service(tmp_path).create(URL, kind="../../escape", now=NOW)  # type: ignore[arg-type]
    with pytest.raises(b.BackupFailure):
        service(tmp_path).create(URL, now=datetime(2026, 1, 1))  # noqa: DTZ001
    assert not list(tmp_path.iterdir())


def test_backup_root_link_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == tmp_path or original(p))
    with pytest.raises(b.BackupFailure, match="links"):
        service(tmp_path).create(URL, now=NOW)


def test_postgres_dump_checks_identity_before_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(url: str, target: object) -> None:
        raise b.BackupFailure("identity mismatch")

    monkeypatch.setattr(b.PostgresTools, "_confirm_target", staticmethod(refuse))
    with pytest.raises(b.BackupFailure, match="identity mismatch"):
        b.PostgresTools().dump(URL, tmp_path / "dump")


def test_default_dump_error_is_sanitized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str, target: object) -> None:
        raise OSError("fake-secret")

    monkeypatch.setattr(b.PostgresTools, "_confirm_target", staticmethod(fail))
    with pytest.raises(b.BackupFailure) as exc:
        b.BackupStore(tmp_path).create(URL, now=NOW)
    assert "fake-secret" not in str(exc.value)


@pytest.mark.parametrize("host_tool", [True, False])
def test_archive_verification_host_and_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host_tool: bool
) -> None:
    import subprocess

    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("shutil.which", lambda name: "pg_restore" if host_tool else None)
    monkeypatch.setattr("subprocess.run", run)
    path = tmp_path / "archive.dump"
    path.write_bytes(b"PGDMP synthetic")
    b.PostgresTools.verify(path)
    assert "--list" in calls[0]
    assert (calls[0][0] == "pg_restore") is host_tool


def test_failed_verifier_exit_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    monkeypatch.setattr(
        "subprocess.run", lambda *args, **kwargs: subprocess.CompletedProcess([], 1)
    )
    with pytest.raises(b.BackupFailure, match="inspection failed"):
        b.BackupStore(tmp_path, dump=dump).create(URL, now=NOW)
    assert not list(tmp_path.rglob("manifest.json"))


@pytest.mark.parametrize("problem", ["timeout", "empty", "permission"])
def test_tool_failures_preserve_last_verified(tmp_path: Path, problem: str) -> None:
    import subprocess

    store = service(tmp_path)
    old = store.create(URL, now=NOW)

    def broken(url: str, path: Path) -> None:
        if problem == "timeout":
            raise subprocess.TimeoutExpired("pg_dump", 600)
        if problem == "permission":
            raise PermissionError("synthetic denial")
        path.write_bytes(b"")

    with pytest.raises(b.BackupFailure):
        b.BackupStore(tmp_path, dump=broken, verify=verify).create(URL, now=NOW)
    assert store.verified(URL) == [old]


@pytest.mark.parametrize(
    "instant", [datetime(2026, 3, 29, 0, 30, tzinfo=UTC), datetime(2026, 10, 25, 0, 30, tzinfo=UTC)]
)
def test_dst_repeated_and_shifted_hours_share_daily_slot(tmp_path: Path, instant: datetime) -> None:
    store = service(tmp_path)
    old = store.create(URL, now=instant)
    latest = store.create(URL, now=instant + timedelta(hours=1))
    assert b.retention_union([old, latest], daily=1, weekly=0, monthly=0) == {latest.directory}


def test_verified_rejects_kind_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(b.BackupFailure):
        service(tmp_path).verified(URL, kind="../manual")  # type: ignore[arg-type]
    assert not list(tmp_path.iterdir())


def test_in_repo_destination_must_stay_gitignored() -> None:
    from app.config import REPO_ROOT

    with pytest.raises(b.BackupFailure, match="gitignored"):
        service(REPO_ROOT / "frontend" / "backup-output")


@pytest.mark.parametrize("docker_id", [b"12345\n", b"99999\n", b"not-an-id\n"])
def test_docker_fallback_requires_same_cluster(
    monkeypatch: pytest.MonkeyPatch, docker_id: bytes
) -> None:
    import subprocess

    monkeypatch.setattr(
        b.PostgresTools, "_cluster_id", staticmethod(lambda url: "12345"), raising=False
    )
    monkeypatch.setattr("shutil.which", lambda name: "docker")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout=docker_id),
    )
    target = parse_target(URL)
    if docker_id == b"12345\n":
        b.PostgresTools._confirm_compose(URL, target)
    else:
        with pytest.raises(b.BackupFailure, match="cluster"):
            b.PostgresTools._confirm_compose(URL, target)

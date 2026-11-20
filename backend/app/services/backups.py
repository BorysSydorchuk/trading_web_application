"""Verified, target-scoped backup storage. No scheduling and no restore into live DBs.

Publication is a directory rename: archive and manifest become visible together.
The local backup root must be private to the OS user (archives contain journal data).
An exclusive scope lock serializes writers/retention. A crash leaves a lock requiring
operator inspection, never an unsafe automatic stale-lock removal.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.engine import make_url

from app.config import REPO_ROOT
from app.system.pg_tools import pg_tool
from app.tools.migrate import DbTarget, dump_plan, parse_target, run_dump, subprocess_runner

Kind = Literal["daily", "manual", "pre-migration"]
KINDS = {"daily", "manual", "pre-migration"}
BRUSSELS = ZoneInfo("Europe/Brussels")
ENTRY = re.compile(r"\d{8}T\d{12}Z-[a-f0-9]{32}")
MANIFEST_KEYS = {"version", "scope", "kind", "created_at", "sha256", "size"}
TIMEOUT = 600


class BackupFailure(Exception):  # noqa: N818 - public backup failure contract
    """Sanitized failure; external stderr/credentials are never exposed."""


def target_key(url: str) -> str:
    """Identity excludes credentials and includes host, port and database."""
    try:
        parsed = make_url(url)
        if parsed.get_backend_name() != "postgresql" or not parsed.database or parsed.query:
            raise ValueError
        target = parse_target(url)
        if not target.user or any("\x00" in x for x in (target.host, target.database, target.user)):
            raise ValueError
        identity = [target.host.lower(), target.port, target.database]
        return hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()
    except Exception:
        raise BackupFailure("Invalid PostgreSQL backup target") from None


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _plain(path: Path) -> bool:
    return not path.is_symlink() and not path.is_junction()


def _directory(path: Path) -> None:
    # Reject links/junctions in every existing ancestor, including configured root.
    for ancestor in (*reversed(path.parents), path):
        if not _plain(ancestor):
            raise BackupFailure("Backup paths must not contain links")
    path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Archive:
    directory: Path
    created_at: datetime

    @property
    def archive(self) -> Path:
        return self.directory / "archive.dump"


def retention_union(
    items: list[Archive], *, daily: int = 14, weekly: int = 8, monthly: int = 6
) -> set[Path]:
    """Latest representative per Brussels day/week/month, plus last good forever."""
    if min(daily, weekly, monthly) < 0:
        raise BackupFailure("Invalid retention counts")
    ordered = sorted(items, key=lambda x: (x.created_at, x.directory.name), reverse=True)
    keep = {ordered[0].directory} if ordered else set()
    for limit, period in ((daily, "day"), (weekly, "week"), (monthly, "month")):
        seen: set[object] = set()
        for item in ordered:
            local = item.created_at.astimezone(BRUSSELS)
            key: object = local.date()
            if period == "week":
                key = local.isocalendar()[:2]
            elif period == "month":
                key = (local.year, local.month)
            if key not in seen and len(seen) < limit:
                keep.add(item.directory)
                seen.add(key)
    return keep


class PostgresTools:
    """Host PostgreSQL tools preferred; Docker only for confirmed local compose target.

    `compose_port` None = native DB mode (app.system.db_mode): Docker is never called and a
    missing pg_dump/pg_restore is a BackupFailure.
    """

    def __init__(self, *, compose_port: int | None = 5432) -> None:
        self.compose_port = compose_port

    def verify_archive(self, path: Path) -> None:
        self.verify(path, docker_allowed=self.compose_port is not None)

    def dump(self, url: str, path: Path) -> None:
        target_key(url)
        target = parse_target(url)
        # A real connection confirms identity before invoking any dump subprocess.
        self._confirm_target(url, target)
        plan = dump_plan(
            target, path, which=pg_tool, compose_dir=REPO_ROOT, compose_port=self.compose_port
        )
        if plan.to_stdout:
            self._confirm_compose(url, target)
        run_dump(plan, path, subprocess_runner)

    @staticmethod
    def _cluster_id(url: str) -> str:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as conn:
                return str(conn.scalar(text("SELECT system_identifier FROM pg_control_system()")))
        finally:
            engine.dispose()

    @staticmethod
    def _confirm_compose(url: str, target: DbTarget) -> None:
        """Never assume a local native server is the compose cluster with the same DB name."""
        expected = PostgresTools._cluster_id(url)
        docker = shutil.which("docker")
        if not docker:
            raise BackupFailure("Docker backup cluster tool unavailable")
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no password in argv
            [
                docker,
                "compose",
                "exec",
                "-T",
                "db",
                "psql",
                "-X",
                "-A",
                "-t",
                "-U",
                target.user,
                "-d",
                target.database,
                "-c",
                "SELECT system_identifier FROM pg_control_system()",
            ],
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        actual = result.stdout.decode("ascii", errors="replace").strip()
        if result.returncode or not expected.isdecimal() or actual != expected:
            raise BackupFailure("Docker backup cluster identity mismatch")

    @staticmethod
    def _confirm_target(url: str, target: DbTarget) -> None:
        from sqlalchemy import create_engine, text

        engine = create_engine(url, connect_args={"connect_timeout": 5})
        try:
            with engine.connect() as conn:
                if conn.scalar(text("SELECT current_database()")) != target.database:
                    raise BackupFailure("Database identity mismatch")
        finally:
            engine.dispose()

    @staticmethod
    def verify(path: Path, *, docker_allowed: bool = True) -> None:
        """Read TOC and all data blocks without connecting to or restoring any DB."""
        tool = pg_tool("pg_restore")
        if not tool and not docker_allowed:
            raise BackupFailure("Native PostgreSQL pg_restore not found (DB_MODE native)")
        for operation in ("--list", "--file=-"):
            argv = (
                [tool, operation, str(path)]
                if tool
                else ["docker", "compose", "exec", "-T", "db", "pg_restore", operation]
            )
            with path.open("rb") as stream:
                result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    argv,
                    stdin=stream if not tool else subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=REPO_ROOT,
                    timeout=TIMEOUT,
                    check=False,
                )
            if result.returncode:
                raise BackupFailure("PostgreSQL archive inspection failed")


class BackupStore:
    """Root is configurable by caller; daily-only retention is explicit after success."""

    def __init__(
        self,
        root: Path,
        *,
        dump: Callable[[str, Path], None] | None = None,
        verify: Callable[[Path], None] | None = None,
        compose_port: int | None = 5432,
    ) -> None:
        self.root = Path(os.path.abspath(root))
        if self.root.is_relative_to(REPO_ROOT) and not self.root.is_relative_to(
            REPO_ROOT / "backups"
        ):
            raise BackupFailure("In-repository backup roots must be inside gitignored backups/")
        tools = PostgresTools(compose_port=compose_port)
        self.dump = dump or tools.dump
        self.verify = verify or tools.verify_archive

    def scope(self, url: str) -> Path:
        return self.root / target_key(url)

    @contextmanager
    def _lock(self, url: str) -> Iterator[Path]:
        scope = self.scope(url)
        _directory(scope)
        lock = scope / ".lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except OSError:
            raise BackupFailure(
                "Backup scope locked or inaccessible; inspect before retry"
            ) from None
        try:
            os.close(descriptor)
            yield scope
        finally:
            lock.unlink()

    def create(
        self,
        url: str,
        *,
        kind: Kind = "daily",
        now: datetime | None = None,
        archive_name: str | None = None,
    ) -> Archive:
        """Dump, verify, fsync both files, then publish together without overwriting."""
        if kind not in KINDS:
            raise BackupFailure("Invalid backup kind")
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise BackupFailure("Backup timestamp must be timezone-aware")
        if archive_name is not None and not ENTRY.fullmatch(archive_name):
            raise BackupFailure("Invalid archive name")
        try:
            with self._lock(url) as scope:
                parent = scope / kind
                _directory(parent)
                name = archive_name or (
                    now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex
                )
                if (parent / name).exists():
                    raise BackupFailure("Archive already published")
                staging = parent / (name + ".partial")
                staging.mkdir(mode=0o700)
                return self._publish(url, kind, now, staging, parent / name)
        except BackupFailure:
            raise
        except Exception:
            raise BackupFailure("Backup failed; archive not confirmed, retention not run") from None

    def _publish(self, url: str, kind: Kind, now: datetime, staging: Path, final: Path) -> Archive:
        try:
            archive = staging / "archive.dump"
            self.dump(url, archive)
            if not _plain(archive) or not archive.is_file() or archive.stat().st_size == 0:
                raise BackupFailure("Backup archive missing or empty")
            self.verify(archive)
            data = {
                "version": 1,
                "scope": target_key(url),
                "kind": kind,
                "created_at": now.astimezone(UTC).isoformat(),
                "sha256": checksum(archive),
                "size": archive.stat().st_size,
            }
            with archive.open("r+b") as stream:
                os.fsync(stream.fileno())
            with (staging / "manifest.json").open("x", encoding="utf-8") as stream:
                json.dump(data, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            staging.rename(final)
            return Archive(final, now.astimezone(UTC))
        finally:
            # Only our newly created staging directory; never an existing archive.
            if staging.exists():
                for name in ("archive.dump", "manifest.json"):
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()

    def verified(self, url: str, *, kind: Kind = "daily") -> list[Archive]:
        """Fail closed on damaged recognized archives; ignore unrelated names."""
        if kind not in KINDS:
            raise BackupFailure("Invalid backup kind")
        parent = self.scope(url) / kind
        _directory(parent)
        result = []
        try:
            for directory in parent.iterdir():
                if ENTRY.fullmatch(directory.name):
                    result.append(self._read(directory, target_key(url), kind))
            return sorted(result, key=lambda x: (x.created_at, x.directory.name), reverse=True)
        except Exception:
            raise BackupFailure("Backup integrity check failed; retention refused") from None

    @staticmethod
    def _read(directory: Path, scope: str, kind: Kind) -> Archive:
        if not _plain(directory) or not directory.is_dir():
            raise BackupFailure("Unsafe archive directory")
        if {p.name for p in directory.iterdir()} != {"archive.dump", "manifest.json"}:
            raise BackupFailure("Unexpected archive contents")
        archive, manifest = directory / "archive.dump", directory / "manifest.json"
        if not all(_plain(p) and p.is_file() for p in (archive, manifest)):
            raise BackupFailure("Unsafe archive files")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            set(data) != MANIFEST_KEYS
            or data["version"] != 1
            or data["scope"] != scope
            or data["kind"] != kind
            or data["size"] != archive.stat().st_size
            or data["size"] <= 0
            or data["sha256"] != checksum(archive)
        ):
            raise BackupFailure("Invalid archive manifest or checksum")
        created = datetime.fromisoformat(data["created_at"])
        if created.tzinfo is None or created.utcoffset() is None:
            raise BackupFailure("Invalid archive timestamp")
        return Archive(directory, created.astimezone(UTC))

    def prune(self, url: str) -> list[Path]:
        """Only daily archives after full integrity scan; never manual/pre-migration."""
        try:
            with self._lock(url):
                items = self.verified(url)
                keep = retention_union(items)
                deleted = []
                for item in items:
                    if item.directory not in keep:
                        # Revalidate immediately before deletion, no recursive removal.
                        self._read(item.directory, target_key(url), "daily")
                        item.archive.unlink()
                        (item.directory / "manifest.json").unlink()
                        item.directory.rmdir()
                        deleted.append(item.directory)
                return deleted
        except BackupFailure:
            raise
        except Exception:
            raise BackupFailure("Backup retention incomplete; inspect archive directory") from None

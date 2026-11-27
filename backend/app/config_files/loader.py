"""Shared plumbing for the editable YAML files in `config/`: location, parsing, errors, cache.

YAML is parsed with two safety tweaks for hand-edited files:
- only `true`/`false` are booleans (YAML 1.2), so `value: no` stays the string "no";
- a duplicate key in a mapping is an error instead of silently overwriting the first one.

Files are read as UTF-8 (a UTF-8 BOM is accepted). Text garbled by a wrong-encoding re-save
(mojibake, see `mojibake.py`) is refused with reason `mojibake` instead of reaching the UI.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.config import REPO_ROOT
from app.config_files.mojibake import mojibake_problems

logger = logging.getLogger(__name__)

CONFIG_DIR_ENV = "CONFIG_DIR"
# `ConfigError.reason` for text garbled by a wrong encoding (API: `details.reason`).
REASON_MOJIBAKE = "mojibake"


class ConfigError(Exception):
    """A config file is missing or invalid. `str()` is a readable, multi-line message.

    `reason` is a stable code for errors the UI shows a specific text for (else None).
    """

    def __init__(self, path: Path, problems: list[str], reason: str | None = None) -> None:
        self.path = path
        self.problems = problems
        self.reason = reason
        lines = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"Invalid config file {path}:\n{lines}")


def config_dir() -> Path:
    """Repo-root `config/`, or `$CONFIG_DIR` (relative paths resolve against the repo root)."""
    raw = os.environ.get(CONFIG_DIR_ENV)
    if not raw:
        return REPO_ROOT / "config"
    path = Path(raw).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans and duplicate-key detection."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if isinstance(key, Hashable) and key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


# Replace the YAML 1.1 bool resolver (yes/no/on/off/...) with YAML 1.2 true/false only.
_StrictLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def read_yaml(path: Path) -> Any:
    """Parse a YAML file; any I/O, encoding or syntax problem becomes a ConfigError."""
    try:
        # utf-8-sig: Windows PowerShell 5.1 `Set-Content -Encoding utf8` writes a BOM.
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ConfigError(path, ["file not found"]) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(path, [f"cannot read file: {exc}"]) from None
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ConfigError(path, [f"YAML syntax error: {exc}"]) from None
    garbled = mojibake_problems(data)
    if garbled:
        raise ConfigError(path, garbled, reason=REASON_MOJIBAKE)
    return data


def _loc(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out or "(root)"


def validation_problems(exc: ValidationError) -> list[str]:
    """One readable line per pydantic error: `dotted.key: message`."""
    problems: list[str] = []
    for err in exc.errors():
        # Pydantic prefixes custom ValueError messages with "Value error, ".
        msg = str(err.get("msg", "invalid")).removeprefix("Value error, ")
        loc = _loc(tuple(err.get("loc", ())))
        # A validator may report several problems, one per line.
        problems.extend(f"{loc}: {line}" for line in msg.splitlines() if line.strip())
    return problems


def file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


@dataclass(frozen=True)
class StaleConfig:
    """A config file whose new content failed validation; the last valid one stays in use."""

    path: Path
    problems: tuple[str, ...]
    since: datetime  # aware UTC, first failure of this content


_stale_lock = threading.Lock()
_stale: dict[Path, StaleConfig] = {}
# Which caches noted each path: only a cache that noted a file clears it (another cache that
# reads the same file, e.g. journal_fields with rules.yaml, may load fine on the stale value).
_owners: dict[Path, set[int]] = {}


def stale_configs() -> list[StaleConfig]:
    """Files not applied right now (owner/PM 2026-11-27: «Конфіг не застосовано»), by path."""
    with _stale_lock:
        return sorted(_stale.values(), key=lambda s: str(s.path))


def _note_stale(owner: int, exc: ConfigError) -> None:
    problems = tuple(exc.problems)
    with _stale_lock:
        _owners.setdefault(exc.path, set()).add(owner)
        known = _stale.get(exc.path)
        if known is not None and known.problems == problems:
            return  # already logged for this content
        _stale[exc.path] = StaleConfig(exc.path, problems, datetime.now(UTC))
    logger.error("CONFIG NOT APPLIED, the last valid version stays in use. %s", exc)


def _clear_stale(owner: int) -> list[Path]:
    """Drop what ``owner`` noted; a path goes when no cache has it noted any more."""
    fixed: list[Path] = []
    with _stale_lock:
        for path, owners in list(_owners.items()):
            if owner not in owners:
                continue
            owners.discard(owner)
            if not owners:
                del _owners[path]
                if _stale.pop(path, None) is not None:
                    fixed.append(path)
    return fixed


def reset_stale() -> None:
    """Forget every noted file (with `reload_config`, tests)."""
    with _stale_lock:
        _stale.clear()
        _owners.clear()


class FileCache[T]:
    """Caches a parsed value until one of its source files changes (mtime/size) or `clear()`.

    Failures are not cached: a fixed file is picked up by the next call without a restart.
    Hardening (owner/PM 2026-11-27): when a CHANGED file fails validation, the last valid
    value of the same files stays in use (sync never stops), the file is listed by
    `stale_configs` and logged once at ERROR. Without any valid value yet (start, or after
    `clear()`), the ConfigError is raised as before.
    """

    def __init__(self, paths: Callable[[], list[Path]], load: Callable[[], T]) -> None:
        self._paths = paths
        self._load = load
        self._lock = threading.Lock()
        self._stamp: tuple[tuple[int, int] | None, ...] | None = None
        self._value: T | None = None
        self._key: tuple[Path, ...] | None = None
        self._good: dict[tuple[Path, ...], T] = {}

    def get(self) -> T:
        with self._lock:
            key = tuple(self._paths())
            stamp = tuple(file_stamp(p) for p in key)
            if self._value is not None and stamp == self._stamp and key == self._key:
                return self._value
            try:
                value = self._load()
            except ConfigError as exc:
                good = self._good.get(key)
                if good is None:
                    raise
                _note_stale(id(self), exc)
                self._value, self._stamp, self._key = good, stamp, key
                return good
            self._good[key] = value
            self._value, self._stamp, self._key = value, stamp, key
            fixed = _clear_stale(id(self))
        for path in fixed:
            logger.info("Config applied again: %s", path)
        return value

    def clear(self) -> None:
        """Forget everything, the last valid value too (tests, explicit reload)."""
        with self._lock:
            self._value = None
            self._stamp = None
            self._key = None
            self._good.clear()
            _clear_stale(id(self))

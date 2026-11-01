"""Shared plumbing for the editable YAML files in `config/`: location, parsing, errors, cache.

YAML is parsed with two safety tweaks for hand-edited files:
- only `true`/`false` are booleans (YAML 1.2), so `value: no` stays the string "no";
- a duplicate key in a mapping is an error instead of silently overwriting the first one.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.config import REPO_ROOT

CONFIG_DIR_ENV = "CONFIG_DIR"


class ConfigError(Exception):
    """A config file is missing or invalid. `str()` is a readable, multi-line message."""

    def __init__(self, path: Path, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
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
    """Parse a YAML file; any I/O or syntax problem becomes a ConfigError."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(path, ["file not found"]) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(path, [f"cannot read file: {exc}"]) from None
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ConfigError(path, [f"YAML syntax error: {exc}"]) from None


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


class FileCache[T]:
    """Caches a parsed value until one of its source files changes (mtime/size) or `clear()`.

    Failures are not cached: a fixed file is picked up by the next call without a restart.
    """

    def __init__(self, paths: Callable[[], list[Path]], load: Callable[[], T]) -> None:
        self._paths = paths
        self._load = load
        self._lock = threading.Lock()
        self._stamp: tuple[tuple[int, int] | None, ...] | None = None
        self._value: T | None = None

    def get(self) -> T:
        with self._lock:
            stamp = tuple(file_stamp(p) for p in self._paths())
            if self._value is None or stamp != self._stamp:
                self._value = self._load()
                self._stamp = stamp
            return self._value

    def clear(self) -> None:
        with self._lock:
            self._value = None
            self._stamp = None

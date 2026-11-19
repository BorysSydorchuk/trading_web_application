"""`config/violations.yaml`: the rule violations a trade can carry (M8-04, docs/api.md
"Violations").

`auto` entries are the keys the rules engine emits (`ENGINE_RULE_KEYS`); `manual` entries are
chosen by the owner. `deprecated` entries stay on old trades and in history stats but are not
selectable on a trade that does not have them. The options of the journal field
`rule_violations` come from this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.config_files.loader import (
    ConfigError,
    FileCache,
    config_dir,
    read_yaml,
    validation_problems,
)
from app.config_files.rules import ENGINE_RULE_KEYS

VIOLATIONS_FILE = "violations.yaml"

ViolationType = Literal["auto", "manual"]
ViolationStatus = Literal["active", "deprecated"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ViolationEntry(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=50)
    label: str = Field(min_length=1)
    type: ViolationType
    status: ViolationStatus

    @property
    def deprecated(self) -> bool:
        return self.status == "deprecated"


class ViolationsConfig(_Strict):
    violations: tuple[ViolationEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        problems: list[str] = []
        keys = [v.key for v in self.violations]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            problems.append(f"duplicate keys: {', '.join(dupes)}")
        if not any(not v.deprecated for v in self.violations):
            problems.append("at least one entry must have status: active")
        active_auto = {v.key for v in self.violations if v.type == "auto" and not v.deprecated}
        for key in ENGINE_RULE_KEYS:
            if key not in active_auto:
                problems.append(
                    f"{key}: the rules engine reports this key, it must be type: auto, "
                    "status: active"
                )
        for key in sorted(active_auto - set(ENGINE_RULE_KEYS)):
            problems.append(
                f"{key}: type auto but the rules engine never reports it "
                "(use type: manual or status: deprecated)"
            )
        if problems:
            raise ValueError("\n".join(problems))
        return self

    def get(self, key: str) -> ViolationEntry | None:
        return next((v for v in self.violations if v.key == key), None)


def violations_path() -> Path:
    return config_dir() / VIOLATIONS_FILE


def load_violations(path: Path | None = None) -> ViolationsConfig:
    """Parse and validate a violations file (uncached). Raises ConfigError."""
    path = path or violations_path()
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(path, ["(root): expected a mapping with a `violations` list"])
    try:
        return ViolationsConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(path, _with_keys(raw, validation_problems(exc))) from None


def _with_keys(raw: dict[str, object], problems: list[str]) -> list[str]:
    """`violations[3].type: ...` -> `violations[3] (my_key).type: ...` for readability."""
    items = raw.get("violations")
    if not isinstance(items, list):
        return problems
    out = []
    for problem in problems:
        for i, item in enumerate(items):
            prefix = f"violations[{i}]"
            if problem.startswith(prefix) and isinstance(item, dict) and "key" in item:
                problem = f"{prefix} ({item['key']}){problem[len(prefix) :]}"
                break
        out.append(problem)
    return out


_cache: FileCache[ViolationsConfig] = FileCache(lambda: [violations_path()], load_violations)


def get_violations() -> ViolationsConfig:
    """Cached violations; reloaded automatically when the file changes. Raises ConfigError."""
    return _cache.get()


def clear_violations_cache() -> None:
    _cache.clear()

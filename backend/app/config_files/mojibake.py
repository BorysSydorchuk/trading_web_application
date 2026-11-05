"""Detect mojibake: UTF-8 text that was decoded with a legacy 8-bit code page.

Typical cause on Windows: a tool read a UTF-8 file as ANSI (cp1251 on a Ukrainian/Russian
locale, cp1252/latin-1 elsewhere) and saved the result as UTF-8 again, so "Тип FVG" became
"РўРёРї FVG" (cp1251) or "Ð¢Ð¸Ð¿ FVG" (latin-1/cp1252).

Test: re-encode the string with the suspected code page and decode the bytes as strict UTF-8.
Real Ukrainian/Russian text practically never survives this (a cp1251 Cyrillic letter is a
UTF-8 lead byte that must be followed by continuation bytes, which are mostly punctuation and
rare letters in cp1251), while mojibake decodes back into different, valid text.
"""

# The examples above are mojibake on purpose (look-alike characters).
# ruff: noqa: RUF002

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

# Code pages a UTF-8 file is commonly misread with on Windows.
SUSPECT_CODEPAGES: tuple[str, ...] = ("cp1251", "cp1252")
# Bytes missing from a code page (cp1251 0x98, cp1252 0x81/0x8D/...) are decoded by Windows
# as the C1 control characters U+0080-U+009F; latin-1 decodes 0x80-0x9F the same way.
_C1_CONTROLS = range(0x80, 0xA0)
# How many garbled strings a ConfigError lists (a re-encoded file garbles all of them).
MAX_REPORTED = 5


def _reencode(text: str, codepage: str) -> bytes | None:
    out = bytearray()
    for char in text:
        try:
            out += char.encode(codepage)
        except UnicodeEncodeError:
            if ord(char) not in _C1_CONTROLS:
                return None  # a character this code page cannot have produced
            out.append(ord(char))
    return bytes(out)


def repair_mojibake(text: str) -> str | None:
    """The original text if `text` looks like mojibake, else None."""
    if text.isascii():
        return None
    for codepage in SUSPECT_CODEPAGES:
        raw = _reencode(text, codepage)
        if raw is None:
            continue
        try:
            fixed = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if fixed != text:
            return fixed
    return None


def _strings(value: Any, loc: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield loc, value
    elif isinstance(value, dict):
        for key, item in value.items():
            child = f"{loc}.{key}" if loc else str(key)
            if isinstance(key, str):
                yield child + " (key)", key
            yield from _strings(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{loc}[{index}]")


def mojibake_problems(data: Any) -> list[str]:
    """One readable line per garbled string (keys and values) in parsed YAML, capped."""
    problems: list[str] = []
    found = 0
    for loc, text in _strings(data, ""):
        fixed = repair_mojibake(text)
        if fixed is None:
            continue
        found += 1
        if found <= MAX_REPORTED:
            problems.append(
                f"{loc or '(root)'}: garbled text {text!r} (looks like {fixed!r} saved in a "
                "wrong encoding)"
            )
    if found > MAX_REPORTED:
        problems.append(f"... and {found - MAX_REPORTED} more garbled strings")
    if problems:
        problems.append(
            "the file was re-saved in a wrong encoding; restore it from git or save it as "
            "UTF-8 with the original text"
        )
    return problems

"""Detect mojibake: UTF-8 text that was decoded with a legacy 8-bit code page.

Typical cause on Windows: a tool read a UTF-8 file as ANSI (cp1251 on a Ukrainian/Russian
locale, cp1252/latin-1 elsewhere) and saved the result as UTF-8 again, so "Тип FVG" became
"РўРёРї FVG" (cp1251) or "Ð¢Ð¸Ð¿ FVG" (latin-1/cp1252).

Test: re-encode the string with the suspected code page and decode the bytes as strict UTF-8.
Short real text can survive the decode ("Ні" is cp1251 CD B3, valid UTF-8 for U+0373), so the
repaired text must also look like real text: at least one letter, and every non-ASCII
character a Cyrillic letter of Ukrainian/Russian (U+0400-U+045F, Ґ/ґ), common typographic
punctuation, or (latin-1/cp1252 path only) a Latin-1 letter. Known residual false positive:
a whole string made only of "Р" + one of Ё Є Ї І і ґ ё є ї Ґ (plus ASCII), e.g. "Рі" -> "г".
"""

# Mojibake examples and the punctuation set use look-alike characters on purpose.
# ruff: noqa: RUF001, RUF002

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

# Code pages a UTF-8 file is commonly misread with on Windows.
SUSPECT_CODEPAGES: tuple[str, ...] = ("cp1251", "cp1252")
# Bytes missing from a code page (cp1251 0x98, cp1252 0x81/0x8D/...) are decoded by Windows
# as the C1 control characters U+0080-U+009F; latin-1 decodes 0x80-0x9F the same way.
_C1_CONTROLS = range(0x80, 0xA0)
# Non-letter characters a repaired (real) text may contain.
_PUNCTUATION = frozenset("–—‘’‚“”„«»№…•·°±ʼ")
_CYRILLIC_BASIC = range(0x0400, 0x0460)
_CYRILLIC_GHE_UPTURN = range(0x0490, 0x0492)
_LATIN1_LETTERS = frozenset(chr(c) for c in range(0xC0, 0x100)) - {"×", "÷"}
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


def _is_cyrillic(char: str) -> bool:
    return ord(char) in _CYRILLIC_BASIC or ord(char) in _CYRILLIC_GHE_UPTURN


def _looks_real(text: str, codepage: str) -> bool:
    """Plausible original text: has a letter, every non-ASCII char is a known letter/sign."""
    latin_ok = codepage != "cp1251"
    letters = 0
    for char in text:
        if char.isascii() or char in _PUNCTUATION:
            continue
        if _is_cyrillic(char) or (latin_ok and char in _LATIN1_LETTERS):
            letters += 1
            continue
        return False
    return letters > 0


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
        if fixed != text and _looks_real(fixed, codepage):
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

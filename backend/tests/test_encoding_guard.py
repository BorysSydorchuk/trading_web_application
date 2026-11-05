"""Text file I/O must name its encoding: Windows' default here is cp1251, not UTF-8 (M3-15).

AST scan of our Python code (ruff's PLW1514 needs preview mode and only sees Path objects
whose type it can infer). A line may opt out with `# allow-default-encoding` (tests only).
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("backend/app", "backend/tests", "backend/alembic", "scripts")
SKIPPED_DIRS = {"__pycache__", ".venv", "node_modules"}
OPT_OUT_MARKERS = ("allow-default-encoding",)
# Modules whose `.open()` is not a text file open (wave/av/webbrowser/tarfile...).
NON_FILE_OPENERS = {"wave", "av", "webbrowser", "tarfile", "zipfile", "gzip", "urllib", "os"}
_TEXT_MODE_KWARGS = ("text", "universal_newlines")
_SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}


@dataclass(frozen=True)
class _Opener:
    mode_pos: int | None  # positional index of `mode` (None: no mode argument)
    encoding_pos: int  # positional index of `encoding`
    text_by_default: bool  # False: binary unless a text mode is passed


_BUILTIN_OPEN = _Opener(1, 3, True)  # open(file, mode, buffering, encoding)
_PATH_OPEN = _Opener(0, 2, True)  # Path.open(mode, buffering, encoding)
_TEMPFILE = _Opener(0, 2, False)  # NamedTemporaryFile/TemporaryFile(mode, buffering, encoding)
# (receiver, name) → opener; receiver None = a bare name (`open(...)`, from-imports).
_OPENERS: dict[tuple[str | None, str], _Opener] = {
    (None, "open"): _BUILTIN_OPEN,
    ("io", "open"): _BUILTIN_OPEN,
    ("builtins", "open"): _BUILTIN_OPEN,
    ("os", "fdopen"): _BUILTIN_OPEN,
    ("codecs", "open"): _Opener(1, 2, True),  # codecs.open(file, mode, encoding)
    **{
        (receiver, name): _TEMPFILE
        for receiver in (None, "tempfile")
        for name in ("NamedTemporaryFile", "TemporaryFile")
    },
    **{(receiver, "SpooledTemporaryFile"): _Opener(1, 3, False) for receiver in (None, "tempfile")},
}


def _const_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _has_kw(call: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in call.keywords) or any(
        kw.arg is None for kw in call.keywords
    )


def _mode(call: ast.Call, mode_pos: int | None) -> ast.expr | None:
    mode = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if mode is None and mode_pos is not None and len(call.args) > mode_pos:
        mode = call.args[mode_pos]
    return mode


def _is_text_mode(call: ast.Call, opener: _Opener) -> bool:
    mode = _mode(call, opener.mode_pos)
    if mode is None:
        return opener.text_by_default
    text = _const_str(mode)
    return text is None or "b" not in text  # a non-literal mode counts as text


def _subprocess_text_without_encoding(call: ast.Call) -> bool:
    func = call.func
    if not (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr in _SUBPROCESS_CALLS
    ):
        return False
    text_mode = any(
        kw.arg in _TEXT_MODE_KWARGS and isinstance(kw.value, ast.Constant) and kw.value.value
        for kw in call.keywords
    )
    return text_mode and not _has_kw(call, "encoding")


def _opener(call: ast.Call) -> _Opener | None:
    func = call.func
    if isinstance(func, ast.Name):
        return _OPENERS.get((None, func.id))
    if not isinstance(func, ast.Attribute):
        return None
    receiver = func.value.id if isinstance(func.value, ast.Name) else None
    if receiver is not None and (receiver, func.attr) in _OPENERS:
        return _OPENERS[(receiver, func.attr)]
    if func.attr == "read_text":
        return _Opener(None, 0, True)
    if func.attr == "write_text":
        return _Opener(None, 1, True)
    if func.attr == "open" and receiver not in NON_FILE_OPENERS:
        return _PATH_OPEN  # any other `<expr>.open(...)`: pathlib.Path.open
    return None


def _lacks_encoding(call: ast.Call) -> bool:
    if _subprocess_text_without_encoding(call):
        return True
    opener = _opener(call)
    if opener is None or _has_kw(call, "encoding") or not _is_text_mode(call, opener):
        return False
    return len(call.args) <= opener.encoding_pos


def unspecified_encodings(source: str, label: str) -> list[str]:
    lines = source.splitlines()
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not _lacks_encoding(node):
            continue
        line = lines[node.lineno - 1]
        if not any(marker in line for marker in OPT_OUT_MARKERS):
            hits.append(f"{label}:{node.lineno}: {line.strip()}")
    return hits


def _python_files() -> list[Path]:
    files: list[Path] = []
    for rel in SCANNED_DIRS:
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT / rel):
            dirnames[:] = [d for d in dirnames if d not in SKIPPED_DIRS]
            files.extend(Path(dirpath) / n for n in filenames if n.endswith(".py"))
    return files


def test_all_text_io_names_its_encoding() -> None:
    files = _python_files()
    scanned = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    assert {"backend/app/config_files/loader.py", "scripts/dev.py"} <= scanned
    hits: list[str] = []
    for path in files:
        label = path.relative_to(REPO_ROOT).as_posix()
        hits += unspecified_encodings(path.read_text(encoding="utf-8"), label)
    assert hits == [], "Pass encoding='utf-8' (Windows default is cp1251):\n" + "\n".join(hits)


def test_scan_flags_missing_encodings() -> None:
    source = "\n".join(
        [
            "open(p)",
            "open(p, 'w')",
            "io.open(p)",
            "CONFIG.read_text()",
            "(ROOT / 'x').write_text(s)",
            "path.open()",
            "path.open('a')",
            "os.fdopen(fd, 'w')",
            "subprocess.run(cmd, text=True)",
            "subprocess.run(cmd, universal_newlines=True)",
            "(ROOT / 'x').open('w')",
            "self.path.open()",
            "tempfile.NamedTemporaryFile('w')",
            "tempfile.NamedTemporaryFile(mode='w+')",
            "NamedTemporaryFile('w')",
            "tempfile.TemporaryFile(mode='w')",
            "tempfile.SpooledTemporaryFile(100, 'w')",
            "tempfile.SpooledTemporaryFile(mode='w+')",
            "codecs.open(p)",
            "codecs.open(p, 'w')",
        ]
    )
    assert len(unspecified_encodings(source, "f")) == source.count("\n") + 1


def test_scan_accepts_explicit_encodings_and_binary() -> None:
    source = "\n".join(
        [
            "open(p, encoding='utf-8')",
            "open(p, 'rb')",
            "open(p, mode='wb')",
            "open(p, 'r', -1, 'utf-8')",
            "path.read_text(encoding='utf-8')",
            "path.read_text('utf-8')",
            "path.write_text(s, 'utf-8')",
            "path.write_text(s, encoding='utf-8', newline='\\n')",
            "path.open('rb')",
            "path.open('a', encoding='utf-8')",
            "os.fdopen(fd, 'w', encoding='utf-8')",
            "os.fdopen(fd, 'wb')",
            "wave.open(str(p), 'wb')",
            "av.open(str(p))",
            "webbrowser.open(URL)",
            "path.read_bytes()",
            "subprocess.run(cmd, capture_output=True)",
            "subprocess.run(cmd, text=True, encoding='utf-8')",
            "reply(text='nope')",
            "open(p, **kwargs)",
            "path.read_text()  # allow-default-encoding: test",
            "(ROOT / 'x').open('rb')",
            "self.path.open('rb')",
            "x.y.open(mode='rb')",
            "tempfile.NamedTemporaryFile()",
            "tempfile.NamedTemporaryFile('wb')",
            "tempfile.NamedTemporaryFile('w', encoding='utf-8')",
            "tempfile.TemporaryFile()",
            "tempfile.SpooledTemporaryFile(100)",
            "tempfile.SpooledTemporaryFile(mode='w', encoding='utf-8')",
            "codecs.open(p, 'r', 'utf-8')",
            "codecs.open(p, encoding='utf-8')",
            "os.open(p, os.O_RDONLY)",
        ]
    )
    assert unspecified_encodings(source, "f") == []

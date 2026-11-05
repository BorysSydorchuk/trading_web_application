"""Text file I/O must name its encoding: Windows' default here is cp1251, not UTF-8 (M3-15).

ruff's PLW1514 (enabled in pyproject.toml) only sees `Path` objects whose type it can infer,
so `CONFIG / "x.yaml"` module constants slip through; this AST scan covers every receiver.
A line may opt out with `# noqa: PLW1514` or `# allow-default-encoding` (tests only).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("backend/app", "backend/tests", "backend/alembic", "scripts")
SKIPPED_DIRS = {"__pycache__", ".venv", "node_modules"}
OPT_OUT_MARKERS = ("noqa: PLW1514", "allow-default-encoding")
# Modules whose `.open()` is not a text file open (wave/av/webbrowser/tarfile...).
NON_FILE_OPENERS = {"wave", "av", "webbrowser", "tarfile", "zipfile", "gzip", "urllib"}
# Calls → index of the positional `encoding` argument and of the positional `mode` argument.
_ENCODING_POS = {"open": 3, "fdopen": 3, "read_text": 0, "write_text": 1}
_MODE_POS = {"open": 1, "fdopen": 1}
_PATH_OPEN_ENCODING_POS = 2  # Path.open(mode, buffering, encoding)
_TEXT_MODE_KWARGS = ("text", "universal_newlines")
_SUBPROCESS_CALLS = {"run", "Popen", "check_output", "check_call", "call"}


def _const_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _has_kw(call: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in call.keywords) or any(
        kw.arg is None for kw in call.keywords
    )


def _is_binary(call: ast.Call, mode_pos: int) -> bool:
    mode = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if mode is None and len(call.args) > mode_pos:
        mode = call.args[mode_pos]
    text = _const_str(mode)
    return text is not None and "b" in text


def _subprocess_text_without_encoding(call: ast.Call) -> bool:
    name, receiver = _call_name(call)
    if receiver != "subprocess" or name not in _SUBPROCESS_CALLS:
        return False
    text_mode = any(
        kw.arg in _TEXT_MODE_KWARGS and isinstance(kw.value, ast.Constant) and kw.value.value
        for kw in call.keywords
    )
    return text_mode and not _has_kw(call, "encoding")


def _call_name(call: ast.Call) -> tuple[str | None, str | None]:
    """(function name, receiver name if it is a plain name) for `f()` / `x.f()`."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id, None
    if isinstance(func, ast.Attribute):
        receiver = func.value.id if isinstance(func.value, ast.Name) else None
        return func.attr, receiver
    return None, None


def _lacks_encoding(call: ast.Call) -> bool:
    if _subprocess_text_without_encoding(call):
        return True
    name, receiver = _call_name(call)
    if name not in _ENCODING_POS or receiver in NON_FILE_OPENERS or _has_kw(call, "encoding"):
        return False
    builtin_style = name == "fdopen" or (name == "open" and receiver in (None, "io", "builtins"))
    if name == "open" and not builtin_style:  # Path.open(mode, buffering, encoding, ...)
        return not _is_binary(call, 0) and len(call.args) <= _PATH_OPEN_ENCODING_POS
    if name in _MODE_POS and _is_binary(call, _MODE_POS[name]):
        return False
    return len(call.args) <= _ENCODING_POS[name]


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
            "open(p)  # noqa: PLW1514",
        ]
    )
    assert unspecified_encodings(source, "f") == []

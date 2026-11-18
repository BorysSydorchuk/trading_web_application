"""M8-12: desktop shortcuts, autostart (Startup folder) and the /api/system endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT
from app.system import shortcuts
from app.system.terminals import terminals_visible

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop only")


class FakeShell:
    """Records the PowerShell calls and writes the .lnk file like WScript.Shell would."""

    def __init__(self) -> None:
        self.envs: list[dict[str, str]] = []

    def __call__(self, args: list[str], env: dict[str, str]) -> None:
        assert args[:2] == ["powershell", "-NoProfile"]
        self.envs.append(env)
        Path(env["TJ_LNK"]).write_bytes(b"lnk")


def test_shortcut_runs_the_tray_under_pythonw_with_the_app_icon(tmp_path: Path) -> None:
    shell = FakeShell()

    shortcuts.write_shortcut(shortcuts.stop_shortcut(tmp_path), shell)

    env = shell.envs[0]
    assert env["TJ_LNK"] == str(tmp_path / "Торговий журнал — Стоп.lnk")
    assert env["TJ_TARGET"].endswith("pythonw.exe")
    assert env["TJ_ARGS"] == f'"{shortcuts.TRAY_SCRIPT}" --stop'
    assert env["TJ_ICON"] == str(shortcuts.ICON_FILE)
    assert env["TJ_WORKDIR"] == str(REPO_ROOT)


def test_autostart_toggle_adds_and_removes_the_startup_shortcut(tmp_path: Path) -> None:
    shell = FakeShell()

    shortcuts.set_autostart(True, tmp_path, shell)
    assert shortcuts.autostart_enabled(tmp_path) is True
    assert shell.envs[0]["TJ_ARGS"].endswith("--autostart")
    shortcuts.set_autostart(True, tmp_path, shell)  # idempotent: rewritten, still one file
    assert len(list(tmp_path.iterdir())) == 1

    shortcuts.set_autostart(False, tmp_path, shell)
    assert shortcuts.autostart_enabled(tmp_path) is False
    shortcuts.set_autostart(False, tmp_path, shell)  # removing twice is fine


def test_a_failed_shell_call_is_a_shortcut_error(tmp_path: Path) -> None:
    def broken(args: list[str], env: dict[str, str]) -> None:
        raise OSError("powershell not found")

    with pytest.raises(shortcuts.ShortcutError, match="powershell not found"):
        shortcuts.write_shortcut(shortcuts.start_shortcut(tmp_path), broken)


def test_api_reports_and_changes_autostart_and_terminal_visibility(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "Startup"
    folder.mkdir()
    shell = FakeShell()
    real_set = shortcuts.set_autostart
    monkeypatch.setattr(shortcuts, "startup_dir", lambda: folder)
    monkeypatch.setattr(
        shortcuts, "set_autostart", lambda enabled: real_set(enabled, folder, shell)
    )

    state = client.get("/api/system/desktop").json()
    assert state == {"supported": True, "autostart": False, "terminals_visible": False}

    assert client.put("/api/system/autostart", json={"enabled": True}).json()["autostart"] is True
    assert (folder / shortcuts.AUTOSTART_NAME).is_file()

    response = client.put("/api/system/terminals", json={"visible": True})
    assert response.json()["terminals_visible"] is True
    from app.config import get_settings

    assert terminals_visible(get_settings().data_dir) is True
    client.put("/api/system/terminals", json={"visible": False})


def test_api_shortcut_failure_is_a_readable_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(enabled: bool) -> None:
        raise shortcuts.ShortcutError("access denied")

    monkeypatch.setattr(shortcuts, "set_autostart", broken)

    response = client.put("/api/system/autostart", json={"enabled": True})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "shortcut_failed"
    assert "access denied" in response.json()["error"]["message"]


def test_api_rejects_a_non_bool(client: TestClient) -> None:
    assert client.put("/api/system/terminals", json={"visible": "yes"}).status_code == 422

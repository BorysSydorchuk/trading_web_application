"""Desktop integration settings (M8-12): «Запускати з Windows» and MT5 terminal windows."""

from __future__ import annotations

import logging
import sys

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.config import get_settings
from app.errors import ApiError
from app.system import shortcuts
from app.system.terminals import set_terminals_visible, terminals_visible

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


class DesktopState(BaseModel):
    supported: bool  # Windows only; elsewhere both toggles are hidden in the UI
    autostart: bool
    terminals_visible: bool


class AutostartInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


class TerminalsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    visible: bool


def _supported() -> bool:
    return sys.platform == "win32"


def _state() -> DesktopState:
    data_dir = get_settings().data_dir
    if not _supported():
        return DesktopState(supported=False, autostart=False, terminals_visible=False)
    try:
        autostart = shortcuts.autostart_enabled()
    except shortcuts.ShortcutError as exc:
        raise ApiError(500, "shortcut_failed", f"Startup folder not available: {exc}") from exc
    return DesktopState(
        supported=True, autostart=autostart, terminals_visible=terminals_visible(data_dir)
    )


def _require_windows() -> None:
    if not _supported():
        raise ApiError(409, "not_supported", "Only available on Windows")


@router.get("/system/desktop", response_model=DesktopState)
def get_desktop() -> DesktopState:
    return _state()


@router.put("/system/autostart", response_model=DesktopState)
def put_autostart(body: AutostartInput) -> DesktopState:
    """Add / remove the Startup-folder shortcut (docs/api.md M8-12)."""
    _require_windows()
    try:
        shortcuts.set_autostart(body.enabled)
    except shortcuts.ShortcutError as exc:
        logger.error("Autostart change failed: %s", exc)
        raise ApiError(500, "shortcut_failed", f"Autostart could not be changed: {exc}") from exc
    return _state()


@router.put("/system/terminals", response_model=DesktopState)
def put_terminals(body: TerminalsInput) -> DesktopState:
    """«Показати / Сховати термінали»: the worker applies it within a few seconds."""
    _require_windows()
    try:
        set_terminals_visible(get_settings().data_dir, body.visible)
    except OSError as exc:
        raise ApiError(500, "internal_error", f"Setting not saved: {exc}") from exc
    return _state()

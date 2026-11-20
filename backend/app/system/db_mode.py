"""Which PostgreSQL the app runs on: the native Windows service or the Docker `db` container.

Decision 2026-11-20 (native-only mode): in `native` mode nothing may call `docker` (no
`docker compose exec` backup fallback, no Docker Desktop start). Docker is used only in
`docker` mode. Resolution (kept identical to `resolve_db_mode` in scripts/dev.py; both are
tested against the same table of cases):

1. an explicit DB_MODE (`native` | `docker`) wins;
2. else `native` when the DATABASE_URL port is NATIVE_PG_PORT (default 5433);
3. else `docker` only for a local host on the Docker POSTGRES_PORT (default 5432);
4. anything else (remote server, another port, unreadable URL) is `native`: never Docker.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.engine import make_url

from app.config import Settings

DbMode = Literal["native", "docker"]
DB_MODES: tuple[DbMode, ...] = ("native", "docker")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
DEFAULT_PORT = 5432


def resolve_db_mode(
    explicit: str | None, host: str, port: int, *, native_port: int, docker_port: int
) -> DbMode:
    """Pure resolution rule; ValueError for an explicit value other than native/docker."""
    if explicit is not None and explicit.strip():
        mode = explicit.strip().lower()
        if mode == "native":
            return "native"
        if mode == "docker":
            return "docker"
        raise ValueError("DB_MODE must be `native` or `docker`")
    if port == native_port:
        return "native"
    if host.lower() in LOCAL_HOSTS and port == docker_port:
        return "docker"
    return "native"


def db_mode(settings: Settings) -> DbMode:
    """Resolved mode of the configured DATABASE_URL (an unreadable URL is never Docker)."""
    try:
        url = make_url(settings.database_url)
        host, port = url.host or "localhost", url.port or DEFAULT_PORT
    except Exception:
        return settings.db_mode or "native"
    return resolve_db_mode(
        settings.db_mode,
        host,
        port,
        native_port=settings.native_pg_port,
        docker_port=settings.postgres_port,
    )


def docker_compose_port(settings: Settings) -> int | None:
    """POSTGRES_PORT when the Docker fallback may be used (docker mode), else None."""
    return settings.postgres_port if db_mode(settings) == "docker" else None

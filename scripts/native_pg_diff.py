"""Read-only row diff between the Docker and the native app database (no secrets printed).

    python -m uv run --project backend python scripts/native_pg_diff.py

For every table in `public`: rows only in Docker, only in native, and rows with the same primary
key but different content (by md5 of the row text, UTC / ISO session settings like `copy`).
Prints table names, primary keys and counts only, never row values. Exit 0 always (diagnostic).
"""

# ruff: noqa: RUF001 - Ukrainian console message

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import native_pg as npg
from native_pg_env import env_values, read_env_text

PK_SQL = """
SELECT a.attname FROM pg_index i
JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY a.attnum
"""


def _rows(cur: Any, table: str) -> dict[str, str]:
    cur.execute(PK_SQL, (f"public.{table}",))
    pk = [r[0] for r in cur.fetchall()]
    key_expr = (
        "concat_ws('|', " + ", ".join(f't."{c}"::text' for c in pk) + ")" if pk else "md5(t::text)"
    )
    cur.execute(f'SELECT {key_expr}, md5(t::text) FROM public."{table}" t')  # noqa: S608 (catalog names)
    return {str(k): str(v) for k, v in cur.fetchall()}


def _snapshot(url: str) -> dict[str, dict[str, str]]:
    with npg.connect(npg.conn_from_url(url)) as conn, conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'; SET DateStyle = 'ISO, YMD'")
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
        tables = [r[0] for r in cur.fetchall()]
        return {t: _rows(cur, t) for t in tables}


def main() -> int:
    env: Mapping[str, str] = env_values(read_env_text(npg.ENV_FILE))
    docker_url = env.get("DOCKER_DATABASE_URL") or env.get("DATABASE_URL", "")
    native_url = env.get("NATIVE_DATABASE_URL", "")
    if not docker_url or not native_url:
        print("[diff] Немає DOCKER_/NATIVE_DATABASE_URL у .env")
        return 0
    docker, native = _snapshot(docker_url), _snapshot(native_url)
    for table in sorted(set(docker) | set(native)):
        d, n = docker.get(table, {}), native.get(table, {})
        only_d = sorted(set(d) - set(n))
        only_n = sorted(set(n) - set(d))
        changed = sorted(k for k in set(d) & set(n) if d[k] != n[k])
        if only_d or only_n or changed:
            print(
                f"{table}: docker={len(d)} native={len(n)} | "
                f"only docker {len(only_d)} {only_d[:15]} | "
                f"only native {len(only_n)} {only_n[:15]} | changed {len(changed)} {changed[:15]}"
            )
        else:
            print(f"{table}: same ({len(d)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

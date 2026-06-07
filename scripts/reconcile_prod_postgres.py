#!/usr/bin/env python3
"""Align .env.prod with an existing Docker Postgres volume and rotate role password."""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.prod"
APP_TABLES = {"agentrun", "projects", "alembic_version", "agent_memories"}


def _read_env(path: Path) -> tuple[list[tuple[str | None, str]], dict[str, str]]:
    lines: list[tuple[str | None, str]] = []
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            lines.append((key, value))
            values[key] = value
        else:
            lines.append((None, raw))
    return lines, values


def _write_env(path: Path, lines: list[tuple[str | None, str]], values: dict[str, str]) -> None:
    seen: set[str] = set()
    out: list[str] = []
    for key, original in lines:
        if key is None:
            out.append(original)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(f"{key}={values.get(key, original)}")
    for key in sorted(set(values) - seen):
        out.append(f"{key}={values[key]}")
    path.write_text("\n".join(out).rstrip() + "\n")
    path.chmod(0o600)


def _run(args: list[str], *, env: dict[str, str] | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, check=check)


def _compose(args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env.prod",
            "-f",
            "docker-compose.prod.yml",
            "-f",
            "docker-compose.dev-override.yml",
            "--profile",
            "standard",
            "--profile",
            "security",
            *args,
        ]
    )


def _db_container() -> str:
    result = _compose(["ps", "-q", "db"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Could not inspect Compose db service.")
    container = result.stdout.strip()
    if not container:
        raise SystemExit("Postgres container is not running; start db before reconciliation.")
    return container


def _psql(container: str, user: str, db: str, sql: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            user,
            "-d",
            db,
            "-At",
            "-c",
            sql,
        ]
    )


def _admin_user(container: str, env_user: str) -> str:
    for user in (env_user, "playwright", "quorvex", "postgres"):
        result = _psql(container, user, "postgres", "select current_user;")
        if result.returncode == 0:
            return user
    raise SystemExit("Could not connect to Postgres through local socket with any known admin role.")


def _rows(result: subprocess.CompletedProcess[str]) -> list[str]:
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _role_exists(container: str, admin: str, role: str) -> bool:
    result = _psql(container, admin, "postgres", f"select 1 from pg_roles where rolname = '{role}';")
    return "1" in _rows(result)


def _databases(container: str, admin: str) -> list[str]:
    result = _psql(
        container,
        admin,
        "postgres",
        "select datname from pg_database where datistemplate = false order by datname;",
    )
    return _rows(result)


def _table_count(container: str, admin: str, db: str) -> int:
    result = _psql(
        container,
        admin,
        db,
        "select count(*) from information_schema.tables where table_schema = 'public';",
    )
    rows = _rows(result)
    return int(rows[0]) if rows and rows[0].isdigit() else 0


def _app_score(container: str, admin: str, db: str) -> int:
    result = _psql(
        container,
        admin,
        db,
        "select table_name from information_schema.tables where table_schema = 'public';",
    )
    return len(APP_TABLES.intersection(_rows(result)))


def _choose_database(container: str, admin: str, env_db: str) -> str:
    databases = _databases(container, admin)
    if env_db in databases:
        return env_db
    candidates = [db for db in ("playwright_agent", "quorvex") if db in databases]
    candidates.extend(db for db in databases if db not in {"postgres", "temporal", "temporal_visibility"})
    if not candidates:
        return env_db
    candidates.sort(key=lambda db: (_app_score(container, admin, db), _table_count(container, admin, db)), reverse=True)
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ENV_FILE))
    args = parser.parse_args()

    env_path = Path(args.env_file)
    lines, values = _read_env(env_path)
    env_user = values.get("POSTGRES_USER") or "playwright"
    env_db = values.get("POSTGRES_DB") or "playwright_agent"
    password = values.get("POSTGRES_PASSWORD") or secrets.token_hex(32)

    container = _db_container()
    admin = _admin_user(container, env_user)

    chosen_user = env_user if _role_exists(container, admin, env_user) else admin
    chosen_db = _choose_database(container, admin, env_db)

    values["POSTGRES_USER"] = chosen_user
    values["POSTGRES_DB"] = chosen_db
    values["POSTGRES_PASSWORD"] = password
    _write_env(env_path, lines, values)

    escaped = password.replace("'", "''")
    alter = _psql(container, admin, "postgres", f"alter role {chosen_user} with password '{escaped}';")
    if alter.returncode != 0:
        raise SystemExit(alter.stderr.strip() or f"Could not alter password for role {chosen_user}.")

    print(f"Postgres env reconciled: user={chosen_user}, database={chosen_db}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

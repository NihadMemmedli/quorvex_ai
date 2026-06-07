#!/usr/bin/env python3
"""Create and repair .env.prod for one-command private-server startup."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.prod"
EXAMPLE_FILE = ROOT / ".env.prod.example"
SECRETS_DIR = ROOT / ".secrets"
GENERATED_FILE = SECRETS_DIR / "generated-prod-credentials.txt"


def _read_env(path: Path) -> tuple[list[tuple[str | None, str]], dict[str, str]]:
    lines: list[tuple[str | None, str]] = []
    values: dict[str, str] = {}
    if not path.exists():
        return lines, values

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


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    return (
        "replace-with" in lowered
        or lowered.startswith("your-")
        or "company.example" in lowered
        or lowered in {"postgres", "minioadmin", "admin123!@#"}
    )


def _secret() -> str:
    return secrets.token_hex(32)


def _set_if_placeholder(values: dict[str, str], key: str, value: str) -> bool:
    if _is_placeholder(values.get(key)):
        values[key] = value
        return True
    return False


def _company_url_from_env() -> str:
    domain = os.environ.get("QUORVEX_DOMAIN", "").strip()
    public_url = os.environ.get("QUORVEX_PUBLIC_URL", "").strip()
    if public_url:
        return public_url.rstrip("/")
    if domain:
        return f"https://{domain}"
    return ""


def main() -> int:
    if not ENV_FILE.exists():
        if not EXAMPLE_FILE.exists():
            raise SystemExit(f"Missing {EXAMPLE_FILE}")
        ENV_FILE.write_text(EXAMPLE_FILE.read_text())
        ENV_FILE.chmod(0o600)
        print("Created .env.prod from .env.prod.example.")

    lines, values = _read_env(ENV_FILE)
    generated: dict[str, str] = {}

    if _set_if_placeholder(values, "POSTGRES_PASSWORD", os.environ.get("POSTGRES_PASSWORD", _secret())):
        generated["POSTGRES_PASSWORD"] = values["POSTGRES_PASSWORD"]
    if _set_if_placeholder(values, "MINIO_ROOT_PASSWORD", os.environ.get("MINIO_ROOT_PASSWORD", _secret())):
        generated["MINIO_ROOT_PASSWORD"] = values["MINIO_ROOT_PASSWORD"]
    if _set_if_placeholder(values, "JWT_SECRET_KEY", os.environ.get("JWT_SECRET_KEY", _secret())):
        generated["JWT_SECRET_KEY"] = values["JWT_SECRET_KEY"]
    if _set_if_placeholder(values, "INITIAL_ADMIN_PASSWORD", os.environ.get("INITIAL_ADMIN_PASSWORD", _secret())):
        generated["INITIAL_ADMIN_PASSWORD"] = values["INITIAL_ADMIN_PASSWORD"]

    values.setdefault("POSTGRES_USER", "playwright")
    values.setdefault("POSTGRES_DB", "playwright_agent")
    values.setdefault("MINIO_ROOT_USER", "quorvex-minio")
    values.setdefault("INITIAL_ADMIN_EMAIL", os.environ.get("INITIAL_ADMIN_EMAIL", "admin@quorvex.local"))
    values.setdefault("REQUIRE_AUTH", "true")
    values.setdefault("ALLOW_REGISTRATION", "false")
    values["NEXT_PUBLIC_API_URL"] = ""
    values["QUORVEX_PUBLIC_API_URL"] = ""
    values.setdefault("NO_PROXY", "localhost,127.0.0.1,db,redis,minio,zap,backend,frontend,temporal,hermes")

    public_url = _company_url_from_env()
    if public_url:
        values["QUORVEX_PUBLIC_URL"] = public_url
        values["ALLOWED_ORIGINS"] = public_url
        values["TEMPORAL_CORS_ORIGINS"] = public_url
        values["VNC_PUBLIC_WS_URL"] = f"{public_url.replace('https://', 'wss://').replace('http://', 'ws://')}/websockify"
    else:
        if _is_placeholder(values.get("ALLOWED_ORIGINS")):
            values["ALLOWED_ORIGINS"] = "http://localhost:3000,http://127.0.0.1:3000"
        if _is_placeholder(values.get("TEMPORAL_CORS_ORIGINS")):
            values["TEMPORAL_CORS_ORIGINS"] = values["ALLOWED_ORIGINS"]
        if _is_placeholder(values.get("VNC_PUBLIC_WS_URL")):
            values["VNC_PUBLIC_WS_URL"] = ""

    for key in ("ZAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HERMES_API_KEY"):
        if os.environ.get(key):
            values[key] = os.environ[key]
        elif _is_placeholder(values.get(key)):
            values[key] = ""

    active_provider = (values.get("QUORVEX_ACTIVE_LLM_PROVIDER") or "zai").lower()
    provider_key = {
        "zai": values.get("ZAI_API_KEY", ""),
        "openrouter": values.get("OPENROUTER_API_KEY", ""),
        "openai": values.get("OPENAI_API_KEY", ""),
        "anthropic": values.get("ANTHROPIC_API_KEY", ""),
    }.get(active_provider, values.get("ZAI_API_KEY", ""))

    if os.environ.get("QUORVEX_LLM_API_KEY"):
        provider_key = os.environ["QUORVEX_LLM_API_KEY"]

    if _is_placeholder(values.get("QUORVEX_LLM_API_KEY")) or os.environ.get("QUORVEX_LLM_API_KEY"):
        values["QUORVEX_LLM_API_KEY"] = provider_key
    if _is_placeholder(values.get("ANTHROPIC_AUTH_TOKEN")) or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        values["ANTHROPIC_AUTH_TOKEN"] = os.environ.get("ANTHROPIC_AUTH_TOKEN", provider_key)
    if _is_placeholder(values.get("ANTHROPIC_API_KEY")) or os.environ.get("ANTHROPIC_API_KEY"):
        values["ANTHROPIC_API_KEY"] = os.environ.get("ANTHROPIC_API_KEY", provider_key)

    _write_env(ENV_FILE, lines, values)

    if generated:
        SECRETS_DIR.mkdir(mode=0o700, exist_ok=True)
        existing = GENERATED_FILE.read_text() if GENERATED_FILE.exists() else ""
        with GENERATED_FILE.open("a") as fh:
            if not existing:
                fh.write("# Generated by scripts/bootstrap_prod_env.py. Keep private.\n")
            for key, value in generated.items():
                fh.write(f"{key}={value}\n")
        GENERATED_FILE.chmod(0o600)
        print(f"Generated private values in {GENERATED_FILE}.")

    print(".env.prod is bootstrapped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

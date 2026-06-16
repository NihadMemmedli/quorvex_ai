from pathlib import Path

import pytest
from fastapi import HTTPException

from orchestrator.api import backup_control


def _point_module_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    module_file = tmp_path / "orchestrator" / "api" / "backup_control.py"
    module_file.parent.mkdir(parents=True)
    monkeypatch.setattr(backup_control, "__file__", str(module_file))
    return tmp_path / "orchestrator" / "data"


@pytest.mark.asyncio
async def test_sqlite_missing_db_returns_404(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    _point_module_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(backup_control, "get_database_type", lambda: "sqlite")

    with pytest.raises(HTTPException) as exc_info:
        await backup_control.create_backup()

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "SQLite database not found"


@pytest.mark.asyncio
async def test_backup_status_empty_sqlite_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    data_dir = _point_module_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(backup_control, "get_database_type", lambda: "sqlite")

    status = await backup_control.get_backup_status()

    assert status == {
        "database_type": "sqlite",
        "backup_dir": str(data_dir / "backups"),
        "backup_count": 0,
        "total_size_bytes": 0,
        "recent_backups": [],
        "retention_days": 30,
    }


@pytest.mark.asyncio
async def test_postgresql_pg_dump_timeout_returns_504(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(backup_control, "get_database_type", lambda: "postgresql")
    monkeypatch.setattr(backup_control, "BASE_DIR", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.test:5433/quorvex")

    def raise_timeout(*args, **kwargs):
        raise backup_control.subprocess.TimeoutExpired(cmd="pg_dump", timeout=300)

    monkeypatch.setattr(backup_control.subprocess, "run", raise_timeout)

    with pytest.raises(HTTPException) as exc_info:
        await backup_control.create_backup()

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "Backup timed out after 5 minutes"


@pytest.mark.asyncio
async def test_postgresql_missing_pg_dump_returns_500(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(backup_control, "get_database_type", lambda: "postgresql")
    monkeypatch.setattr(backup_control, "BASE_DIR", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example.test:5433/quorvex")

    def raise_missing_binary(*args, **kwargs):
        raise FileNotFoundError("pg_dump")

    monkeypatch.setattr(backup_control.subprocess, "run", raise_missing_binary)

    with pytest.raises(HTTPException) as exc_info:
        await backup_control.create_backup()

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "pg_dump not found. Backup must be run from a container with PostgreSQL tools."


def test_backup_routes_registered_from_backup_control():
    from orchestrator.api.main import app

    endpoints = {
        (method, route.path): route.endpoint.__module__
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }

    assert endpoints[("POST", "/api/backup")] == "orchestrator.api.backup_control"
    assert endpoints[("GET", "/api/backup/status")] == "orchestrator.api.backup_control"


def test_main_has_no_direct_http_route_decorators():
    main_source = (Path(__file__).parent.parent / "api" / "main.py").read_text()

    for decorator in ("@app.get", "@app.post", "@app.put", "@app.delete", "@app.patch"):
        assert decorator not in main_source

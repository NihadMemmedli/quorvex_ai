import os
import sys
import types
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci-subset-e2e")

slowapi = types.ModuleType("slowapi")
slowapi_errors = types.ModuleType("slowapi.errors")
slowapi_util = types.ModuleType("slowapi.util")


class _Limiter:
    def __init__(self, *args, **kwargs):
        self._storage = types.SimpleNamespace(expirations={})


class _RateLimitExceeded(Exception):
    retry_after = 60


slowapi.Limiter = _Limiter
slowapi_errors.RateLimitExceeded = _RateLimitExceeded
slowapi_util.get_remote_address = lambda request: "test-client"
sys.modules.setdefault("slowapi", slowapi)
sys.modules.setdefault("slowapi.errors", slowapi_errors)
sys.modules.setdefault("slowapi.util", slowapi_util)

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.api import ci_control
from orchestrator.api.models_db import Project, SpecMetadata


class FakeGithubClient:
    def __init__(self):
        self.created_refs: list[tuple[str, str]] = []
        self.written_files: dict[str, str] = {}
        self.dispatched: list[dict] = []

    async def get_ref(self, owner: str, repo: str, ref: str):
        return {"object": {"sha": "base-sha"}}

    async def create_ref(self, owner: str, repo: str, ref: str, sha: str):
        self.created_refs.append((ref, sha))
        return {"ref": ref}

    async def get_content_metadata(self, owner: str, repo: str, path: str, ref: str | None = None):
        return None

    async def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        content: str,
        message: str,
        branch: str,
        sha: str | None = None,
    ):
        self.written_files[path] = content
        return {"content": {"sha": f"sha-{path}"}, "commit": {"sha": "commit-sha"}}

    async def list_pull_requests(self, owner: str, repo: str, **kwargs):
        return []

    async def create_pull_request(self, owner: str, repo: str, **kwargs):
        return {"html_url": "https://github.example/acme/app/pull/77", "number": 77, **kwargs}

    async def trigger_workflow(self, owner: str, repo: str, workflow_id: str, ref: str, inputs: dict | None = None):
        self.dispatched.append({"workflow_id": workflow_id, "ref": ref, "inputs": inputs})
        return True

    async def get_workflow_runs(self, owner: str, repo: str, workflow_id: str | None = None, per_page: int = 5):
        run_id = 12344 + len(self.dispatched)
        return [
            {
                "id": run_id,
                "html_url": f"https://github.example/acme/app/actions/runs/{run_id}",
                "head_branch": "main",
                "path": ".github/workflows/quorvex-subset-tests.yml",
                "status": "queued",
            }
        ]

    async def close(self):
        return None


def test_chat_controlled_ci_subset_flow_end_to_end(monkeypatch, tmp_path):
    project_root = tmp_path / "repo"
    specs_dir = project_root / "specs"
    tests_dir = project_root / "tests" / "generated"
    specs_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    (specs_dir / "checkout.md").write_text("# Checkout smoke\n\n1. Complete checkout.\n", encoding="utf-8")
    generated_test = tests_dir / "checkout.spec.ts"
    generated_test.write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('checkout smoke', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(ci_control, "BASE_DIR", project_root)
    monkeypatch.setattr(ci_control, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(ci_control, "_get_try_code_path", lambda _spec_name, _spec_path: str(generated_test))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    fake_github = FakeGithubClient()

    def override_session():
        with Session(engine) as session:
            yield session

    async def fake_build_client(_project):
        return fake_github

    monkeypatch.setattr(ci_control, "_build_github_client", fake_build_client)

    with Session(engine) as session:
        project = Project(
            id="default",
            name="Default",
            base_url="https://app.example.test",
            settings={
                "integrations": {
                    "github": {
                        "owner": "acme",
                        "repo": "app",
                        "default_ref": "main",
                        "default_workflow": "quorvex-subset-tests.yml",
                        "token_encrypted": "unused-in-test",
                    }
                }
            },
        )
        meta = SpecMetadata(spec_name="checkout.md", project_id="default")
        meta.tags = ["smoke", "critical"]
        session.add(project)
        session.add(meta)
        session.commit()

    app = FastAPI()
    app.include_router(ci_control.router)
    app.dependency_overrides[ci_control.get_session] = override_session

    with TestClient(app, raise_server_exceptions=False) as client:
        generated = client.get("/projects/default/ci/generated-tests")
        assert generated.status_code == 200
        assert generated.json()["tests"][0]["spec_name"] == "checkout.md"
        assert generated.json()["tests"][0]["target_path"] == "tests/generated/checkout.spec.ts"

        created = client.post(
            "/projects/default/ci/test-subsets",
            json={
                "name": "Checkout Smoke",
                "description": "Chat-selected checkout tests",
                "mode": "both",
                "default_browser": "chromium",
                "base_url_secret": "APP_BASE_URL",
                "items": [{"spec_name": "checkout.md"}],
            },
        )
        assert created.status_code == 200
        subset = created.json()
        assert subset["slug"] == "checkout-smoke"
        assert subset["item_count"] == 1

        preview = client.post(f"/projects/default/ci/test-subsets/{subset['id']}/preview")
        assert preview.status_code == 200
        assert preview.json()["manifest_path"] == ".quorvex/test-subsets/checkout-smoke.json"

        opened = client.post(
            f"/projects/default/ci/test-subsets/{subset['id']}/pull-request",
            json={"draft": True, "workflow_name": "Quorvex Checkout Smoke"},
        )
        assert opened.status_code == 200
        assert opened.json()["pull_request_number"] == 77
        assert "tests/generated/checkout.spec.ts" in fake_github.written_files
        assert ".quorvex/test-subsets/checkout-smoke.json" in fake_github.written_files
        assert ".github/workflows/quorvex-subset-tests.yml" in fake_github.written_files
        assert "playwright.config.ts" in fake_github.written_files
        assert "package.json" in fake_github.written_files
        assert "pr-advisor/analyze" in fake_github.written_files[".github/workflows/quorvex-subset-tests.yml"]

        dispatched = client.post(
            f"/projects/default/ci/test-subsets/{subset['id']}/dispatch",
            json={"browser": "firefox"},
        )
        assert dispatched.status_code == 200
        assert dispatched.json()["run"]["external_pipeline_id"] == "12345"
        assert fake_github.dispatched[-1]["inputs"] == {
            "subset_slug": "checkout-smoke",
            "browser": "firefox",
            "base_url": "https://app.example.test",
        }


def test_workflow_dispatch_injects_project_base_url_only_for_subset_workflows(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    fake_github = FakeGithubClient()

    def override_session():
        with Session(engine) as session:
            yield session

    async def fake_build_client(_project):
        return fake_github

    monkeypatch.setattr(ci_control, "_build_github_client", fake_build_client)

    with Session(engine) as session:
        session.add(
            Project(
                id="default",
                name="Default",
                base_url="https://app.example.test",
                settings={
                    "integrations": {
                        "github": {
                            "owner": "acme",
                            "repo": "app",
                            "default_ref": "main",
                            "token_encrypted": "unused-in-test",
                        }
                    }
                },
            )
        )
        session.commit()

    app = FastAPI()
    app.include_router(ci_control.router)
    app.dependency_overrides[ci_control.get_session] = override_session

    with TestClient(app, raise_server_exceptions=False) as client:
        subset_response = client.post(
            "/projects/default/ci/workflows/dispatch",
            json={
                "provider": "github",
                "workflow_id": "quorvex-subset-tests.yml",
                "inputs": {"suite": "playwright-e2e"},
            },
        )
        assert subset_response.status_code == 200, subset_response.text
        assert fake_github.dispatched[-1]["inputs"] == {
            "suite": "playwright-e2e",
            "browser": "chromium",
            "pytest_marker": "not integration",
            "base_url": "https://app.example.test",
        }

        arbitrary_response = client.post(
            "/projects/default/ci/workflows/dispatch",
            json={
                "provider": "github",
                "workflow_id": "deploy.yml",
                "inputs": {"environment": "staging"},
            },
        )
        assert arbitrary_response.status_code == 200, arbitrary_response.text
        assert fake_github.dispatched[-1]["inputs"] == {"environment": "staging"}

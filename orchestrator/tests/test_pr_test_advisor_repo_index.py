from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from orchestrator.api.models_db import (
    PrChangedFile,
    PrImpactAnalysis,
    Project,
    PrSelectedTest,
    RepoIndexedFile,
    RepoIndexSnapshot,
)
from orchestrator.api.models_db import TestImpactMap as _TestImpactMap
from orchestrator.services.pr_test_advisor import (
    ChangedFileInput,
    RepoFileInput,
    analyze_pr_changes,
    index_repository_snapshot,
    select_impacted_tests,
)
from orchestrator.services.pr_test_advisor import (
    TestInventoryItem as _TestInventoryItem,
)


def _item(name: str) -> _TestInventoryItem:
    return _TestInventoryItem(
        spec_name=name,
        spec_path=Path("specs") / name,
        test_path=f"tests/generated/{Path(name).stem}.spec.ts",
    )


def _indexed_file(
    path: str,
    *,
    imports: list[str] | None = None,
    routes: list[str] | None = None,
    kind: str = "source",
) -> dict[str, object]:
    return {
        "path": path,
        "imports": imports or [],
        "routes": routes or [],
        "kind": kind,
    }


def test_repo_index_import_graph_selects_route_test_for_changed_source_file():
    changed_files = [
        ChangedFileInput(
            path="web/src/lib/pricing/calculate-total.ts",
            status="modified",
            changes=9,
        )
    ]
    inventory = [
        _item("billing-checkout.md"),
        _item("profile-settings.md"),
    ]
    repo_index = {
        "files": [
            _indexed_file("web/src/lib/pricing/calculate-total.ts"),
            _indexed_file(
                "web/src/components/BillingSummary.tsx",
                imports=["web/src/lib/pricing/calculate-total.ts", "@/lib/pricing/calculate-total"],
                routes=["/billing"],
                kind="component",
            ),
            _indexed_file(
                "web/src/app/billing/page.tsx",
                imports=["web/src/components/BillingSummary.tsx", "@/components/BillingSummary"],
                routes=["/billing"],
                kind="route",
            ),
        ]
    }

    result = select_impacted_tests(changed_files, inventory, repo_index=repo_index)

    selected = {test.spec_name: test for test in result.selected_tests}
    assert set(selected) == {"billing-checkout.md"}
    assert result.fallback_reason is None
    assert result.confidence in {"medium", "high"}
    assert "repo_index" in selected["billing-checkout.md"].selection_source


def test_no_repo_index_for_shared_source_change_uses_conservative_fallback():
    changed_files = [
        ChangedFileInput(
            path="web/src/lib/pricing/calculate-total.ts",
            status="modified",
            changes=9,
        )
    ]
    inventory = [
        _item("billing-checkout.md"),
        _item("profile-settings.md"),
        _item("admin-audit.md"),
    ]

    result = select_impacted_tests(changed_files, inventory)

    assert result.confidence == "low"
    assert result.risk_level == "high"
    assert result.fallback_reason
    assert {test.spec_name for test in result.selected_tests} == {item.spec_name for item in inventory}
    assert {test.selection_source for test in result.selected_tests} == {"full_suite_fallback"}


def test_unknown_source_change_uses_conservative_fallback_even_with_unrelated_index():
    changed_files = [
        ChangedFileInput(
            path="packages/shared/pricing/calculate-total.ts",
            status="modified",
            changes=6,
        )
    ]
    inventory = [
        _item("billing-checkout.md"),
        _item("profile-settings.md"),
    ]
    repo_index = {
        "files": [
            _indexed_file(
                "web/src/app/profile/page.tsx",
                imports=["web/src/lib/profile/load-profile"],
                routes=["/profile"],
                kind="route",
            )
        ]
    }

    result = select_impacted_tests(changed_files, inventory, repo_index=repo_index)

    assert result.confidence == "low"
    assert result.risk_level == "high"
    assert result.fallback_reason
    assert {test.spec_name for test in result.selected_tests} == {item.spec_name for item in inventory}
    assert {test.selection_source for test in result.selected_tests} == {"full_suite_fallback"}


def test_repository_index_snapshot_persists_files_and_derived_impact_maps(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    import orchestrator.services.pr_test_advisor as advisor

    inventory = [
        _TestInventoryItem(
            spec_name="billing-checkout.md",
            spec_path=Path("specs/billing-checkout.md"),
            test_path="tests/generated/billing-checkout.spec.ts",
            tags=[],
            categories=[],
        )
    ]
    monkeypatch.setattr(advisor, "build_test_inventory", lambda project_id, session: inventory)

    files = [
        RepoFileInput(
            path="web/src/lib/pricing/calculate-total.ts",
            sha="sha-lib",
            size=120,
            content="export function calculateTotal() { return 1; }",
        ),
        RepoFileInput(
            path="web/src/components/BillingSummary.tsx",
            sha="sha-component",
            size=200,
            content="import { calculateTotal } from '@/lib/pricing/calculate-total'; export function BillingSummary() {}",
        ),
        RepoFileInput(
            path="web/src/app/billing/page.tsx",
            sha="sha-route",
            size=180,
            content="import { BillingSummary } from '@/components/BillingSummary'; export default function Page() {}",
        ),
    ]

    with Session(engine) as session:
        session.add(Project(id="default", name="Default"))
        session.commit()

        result = index_repository_snapshot(
            project_id="default",
            owner="org",
            repo="app",
            ref="main",
            commit_sha="commit-1",
            files=files,
            session=session,
        )

        snapshot = session.get(RepoIndexSnapshot, result.snapshot.id)
        indexed_files = session.exec(select(RepoIndexedFile).where(RepoIndexedFile.snapshot_id == result.snapshot.id)).all()
        impact = session.exec(select(_TestImpactMap).where(_TestImpactMap.spec_name == "billing-checkout.md")).first()

        assert snapshot is not None
        assert snapshot.indexed_files_count == 3
        assert snapshot.route_count == 1
        assert len(indexed_files) == 3
        assert impact is not None
        assert "web/src/lib/pricing/calculate-total.ts" in (impact.impacted_paths or [])
        assert "web/src/app/billing/page.tsx" in (impact.impacted_paths or [])


def test_analyze_pr_changes_persists_parent_before_child_rows(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    import orchestrator.services.pr_test_advisor as advisor

    inventory = [
        _TestInventoryItem(
            spec_name="billing-checkout.md",
            spec_path=Path("specs/billing-checkout.md"),
            test_path="tests/generated/billing-checkout.spec.ts",
            tags=[],
            categories=["billing"],
        )
    ]
    monkeypatch.setattr(advisor, "build_test_inventory", lambda project_id, session: inventory)

    with Session(engine) as session:
        session.add(Project(id="default", name="Default"))
        session.commit()

        analysis = analyze_pr_changes(
            project_id="default",
            owner="org",
            repo="app",
            pr_number=76,
            pr_data={
                "title": "Dependency update",
                "base": {"ref": "main"},
                "head": {"ref": "branch", "sha": "abc"},
                "user": {"login": "dev"},
            },
            changed_files=[
                {
                    "filename": "orchestrator/requirements.txt",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "changes": 2,
                }
            ],
            session=session,
        )

        parent = session.get(PrImpactAnalysis, analysis.id)
        changed = session.exec(select(PrChangedFile).where(PrChangedFile.analysis_id == analysis.id)).all()
        selected = session.exec(select(PrSelectedTest).where(PrSelectedTest.analysis_id == analysis.id)).all()

        assert parent is not None
        assert changed and changed[0].path == "orchestrator/requirements.txt"
        assert selected and selected[0].selection_source == "full_suite_fallback"

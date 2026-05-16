from pathlib import Path

from orchestrator.services.pr_test_advisor import (
    ChangedFileInput,
    TestInventoryItem as _TestInventoryItem,
    classify_changed_file,
    select_impacted_tests,
)


def _item(name: str, tags: list[str] | None = None, categories: list[str] | None = None) -> _TestInventoryItem:
    return _TestInventoryItem(
        spec_name=name,
        spec_path=Path("specs") / name,
        test_path=f"tests/generated/{Path(name).stem}.spec.ts",
        tags=tags or [],
        categories=categories or [],
    )


def test_config_change_falls_back_to_full_suite():
    files = [ChangedFileInput(path="package-lock.json", status="modified", changes=12)]
    inventory = [
        _item("login-smoke.md", tags=["smoke"]),
        _item("checkout-flow.md", tags=["e2e"]),
        _item("api-contract.md", tags=["api"]),
    ]

    result = select_impacted_tests(files, inventory)

    assert result.confidence == "low"
    assert result.risk_level == "high"
    assert result.fallback_reason
    assert {t.spec_name for t in result.selected_tests} == {i.spec_name for i in inventory}


def test_direct_spec_change_selects_matching_test_only_plus_always_run():
    files = [ChangedFileInput(path="specs/checkout-flow.md", status="modified", changes=4)]
    inventory = [
        _item("login-smoke.md", tags=["smoke"]),
        _item("checkout-flow.md", tags=["e2e"]),
        _item("api-contract.md", tags=["api"]),
    ]

    result = select_impacted_tests(files, inventory)

    selected = {t.spec_name: t for t in result.selected_tests}
    assert "checkout-flow.md" in selected
    assert "login-smoke.md" in selected
    assert "api-contract.md" not in selected
    assert selected["checkout-flow.md"].confidence == "high"
    assert result.fallback_reason is None


def test_frontend_route_change_uses_route_and_metadata_rules():
    files = [ChangedFileInput(path="web/src/app/services/page.tsx", status="modified", changes=8)]
    inventory = [
        _item("services-browse.md", tags=["e2e"], categories=["navigation"]),
        _item("database-health.md", tags=["database"]),
    ]

    result = select_impacted_tests(files, inventory)

    assert [t.spec_name for t in result.selected_tests] == ["services-browse.md"]
    assert result.selected_tests[0].selection_source in {"route_rule", "path_rule", "route_rule,path_rule"}
    assert result.confidence in {"medium", "high"}


def test_changed_file_classification_marks_backend_api():
    info = classify_changed_file(ChangedFileInput(path="orchestrator/api/github_ci.py"))

    assert info["area"] == "backend_api"
    assert info["risk_level"] == "medium"

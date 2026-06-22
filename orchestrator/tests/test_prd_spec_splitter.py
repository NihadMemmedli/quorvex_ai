import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.prd_spec_splitter import PRDSpecSplitter
from orchestrator.workflows.full_native_pipeline import FullNativePipeline

PARENT_TARGET_URL = "https://pre.wetravel.to/"
PARENT_ORIGIN = "https://pre.wetravel.to"


def _rich_case(**overrides):
    case = {
        "id": "TC-001",
        "name": "Dashboard flow",
        "category": "Happy Path",
        "content": "",
        "_ai_extracted": True,
        "_description": "Verify dashboard flow",
        "_preconditions": [],
        "_steps": ["Click Create"],
        "_expected_results": ["Flow succeeds"],
        "_selectors": [],
        "_url": None,
    }
    case.update(overrides)
    return case


def _render_rich(case, shared_context=""):
    return PRDSpecSplitter._create_rich_individual_spec(
        test_case=case,
        app_overview="App overview",
        source_spec="parent.md",
        parent_target_url=PARENT_TARGET_URL,
        base_url_origin=PARENT_ORIGIN,
        shared_context=shared_context,
    )


def _write_standard_multi_spec(tmp_path: Path) -> Path:
    spec_path = tmp_path / "multi.md"
    spec_path.write_text(
        """# Test: First flow

## Source
Test ID: TC-001
Category: Happy Path

## Steps
1. Navigate to /

## Expected Outcome
- First flow succeeds

# Test: Second flow

## Source
Test ID: TC-002
Category: Happy Path

## Steps
1. Click Continue

## Expected Outcome
- Second flow succeeds
""",
        encoding="utf-8",
    )
    return spec_path


def test_regex_split_skips_ai_extraction(tmp_path, monkeypatch):
    spec_path = _write_standard_multi_spec(tmp_path)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("AI extraction should not be called for regex split")

    monkeypatch.setattr(
        "orchestrator.utils.ai_spec_splitter.AISpecSplitter.extract_and_group",
        fail_if_called,
    )

    files, groups, metadata = PRDSpecSplitter.split_spec(
        spec_path,
        use_ai=False,
        return_metadata=True,
    )

    assert len(files) == 2
    assert groups is None
    assert metadata["extraction_method"] == "regex"
    assert metadata["ai_used"] is False


def test_strict_ai_split_does_not_fall_back_to_regex(tmp_path, monkeypatch):
    spec_path = _write_standard_multi_spec(tmp_path)
    regex_called = False

    def fail_ai(*_args, **_kwargs):
        raise RuntimeError("missing test key")

    def mark_regex_called(*_args, **_kwargs):
        nonlocal regex_called
        regex_called = True
        return []

    monkeypatch.setattr(
        "orchestrator.utils.ai_spec_splitter.AISpecSplitter.extract_and_group",
        fail_ai,
    )
    monkeypatch.setattr(
        "orchestrator.utils.prd_spec_splitter.SpecDetector.extract_test_cases",
        mark_regex_called,
    )

    with pytest.raises(RuntimeError, match="missing test key"):
        PRDSpecSplitter.split_spec(
            spec_path,
            use_ai=True,
            ai_fallback=False,
            return_metadata=True,
        )

    assert regex_called is False


def test_ai_split_receives_settings_backed_runtime_env(tmp_path, monkeypatch):
    spec_path = _write_standard_multi_spec(tmp_path)
    captured_env = None

    def fake_extract_and_group(_content, _spec_name="", runtime_env_vars=None):
        nonlocal captured_env
        captured_env = runtime_env_vars
        return (
            [
                {"id": "TC-001", "name": "AI first flow", "category": "Happy Path", "content": "First"},
                {"id": "TC-002", "name": "AI second flow", "category": "Happy Path", "content": "Second"},
            ],
            [{"name": "Happy flows", "test_ids": ["TC-001", "TC-002"], "description": "AI grouped flows"}],
        )

    monkeypatch.setattr(
        "orchestrator.utils.ai_spec_splitter.AISpecSplitter.extract_and_group",
        fake_extract_and_group,
    )

    files, groups, metadata = PRDSpecSplitter.split_spec(
        spec_path,
        use_ai=True,
        runtime_env_vars={"QUORVEX_LLM_API_KEY": "settings-key"},
        ai_fallback=False,
        return_metadata=True,
    )

    assert len(files) == 2
    assert groups == [{"name": "Happy flows", "test_ids": ["TC-001", "TC-002"], "description": "AI grouped flows"}]
    assert captured_env == {"QUORVEX_LLM_API_KEY": "settings-key"}
    assert metadata["extraction_method"] == "ai"
    assert metadata["ai_used"] is True


def test_child_with_dashboard_precondition_starts_at_resolved_deep_link():
    spec = _render_rich(
        _rich_case(
            _preconditions=["User is logged in and on the My Trips dashboard (`/user/my_trips`)"],
            _steps=["Click the Create link"],
        )
    )

    assert "- URL: https://pre.wetravel.to/user/my_trips" in spec
    assert "1. Navigate to https://pre.wetravel.to/user/my_trips" in spec
    assert "2. Click the Create link" in spec


def test_child_with_explicit_url_preserves_it():
    spec = _render_rich(
        _rich_case(
            _url="https://pre.wetravel.to/itinerary_builder/create",
            _preconditions=["User is logged in and on the My Trips dashboard (`/user/my_trips`)"],
        )
    )

    assert "Target URL: https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "- URL: https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "1. Navigate to https://pre.wetravel.to/itinerary_builder/create" in spec


def test_relative_navigation_step_is_resolved():
    spec = _render_rich(
        _rich_case(
            _steps=["Navigate to /itinerary_builder/create", "Verify creation cards are visible"],
        )
    )

    assert "Target URL: https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "- URL: https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "1. Navigate to https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "Navigate to /itinerary_builder/create" not in spec


def test_native_pipeline_extracts_url_from_split_child_target_url_line():
    spec = _render_rich(_rich_case(_url="/dashboard"))
    pipeline = object.__new__(FullNativePipeline)

    assert "Target URL: https://pre.wetravel.to/dashboard" in spec
    assert pipeline._extract_url(spec) == "https://pre.wetravel.to/dashboard"


def test_auth_required_non_login_child_keeps_login_and_testdata_context():
    spec = _render_rich(
        _rich_case(
            _preconditions=["Seed account exists"],
            _steps=["Open dashboard", "Verify account summary"],
            _url="/dashboard",
        ),
        shared_context='## Test Data Requirements\n@testdata "Wetravel-Login-Users.valid-user"',
    )

    assert '@testdata "Wetravel-Login-Users.valid-user"' in spec
    assert '@include "templates/login.md"' in spec
    assert "- URL: https://pre.wetravel.to/dashboard" in spec
    assert "1. Navigate to https://pre.wetravel.to/dashboard" in spec


def test_login_case_with_own_url_does_not_get_extra_login_include():
    spec = _render_rich(
        _rich_case(
            name="Login with valid credentials",
            _preconditions=["User has a registered account"],
            _steps=["Navigate to https://pre.wetravel.to/", "Open Sign In", "Submit credentials"],
            _url="https://pre.wetravel.to/",
        )
    )

    assert "- URL: https://pre.wetravel.to/" in spec
    assert '@include "templates/login.md"' not in spec


def test_wetravel_tc002_shape_gets_standalone_dashboard_url_and_clean_markdown():
    test_case = {
        "id": "TC-002",
        "name": "Navigate from dashboard to the trip creation type selection page",
        "category": "Happy Path",
        "content": """### TC-002: Navigate from dashboard to the trip creation type selection page

**Description:** Verify that clicking "Create" in the navigation opens the trip creation type selection page.

**Preconditions:**
- User is logged in and on the My Trips dashboard (`/user/my_trips`)

**Steps:**
1. Click the "Create" link in the navigation menu
2. Verify the page URL is `/itinerary_builder/create`

**Expected Result:**
- User navigates to the trip creation type selection page
""",
    }

    spec = PRDSpecSplitter._create_individual_spec(
        test_case=test_case,
        app_overview="App overview",
        source_spec="req-001-users-must-be-able-to-create-a-new-trip-program.md",
        parent_target_url=PARENT_TARGET_URL,
        base_url_origin=PARENT_ORIGIN,
    )

    assert "## Description\nVerify that clicking" in spec
    assert "- **" not in spec
    assert "- URL: https://pre.wetravel.to/user/my_trips" in spec
    assert "1. Navigate to https://pre.wetravel.to/user/my_trips" in spec
    assert "2. Click the \"Create\" link in the navigation menu" in spec

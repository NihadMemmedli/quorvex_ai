import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.prd_spec_splitter import PRDSpecSplitter


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

    assert "- URL: https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "1. Navigate to https://pre.wetravel.to/itinerary_builder/create" in spec


def test_relative_navigation_step_is_resolved():
    spec = _render_rich(
        _rich_case(
            _steps=["Navigate to /itinerary_builder/create", "Verify creation cards are visible"],
        )
    )

    assert "- URL: https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "1. Navigate to https://pre.wetravel.to/itinerary_builder/create" in spec
    assert "Navigate to /itinerary_builder/create" not in spec


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

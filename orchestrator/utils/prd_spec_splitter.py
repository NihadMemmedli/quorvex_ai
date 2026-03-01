"""
Multi-Test Spec Splitter - Extracts individual test cases from PRD or Native Plan specs

This utility helps convert multi-test specs into individual
spec files that can be run independently.

Supports two extraction modes:
1. Regex-based (fast, free) - works for standard PRD/Native Plan formats
2. AI-powered (fallback) - handles any non-standard format via LLM
"""

import re
from pathlib import Path

from orchestrator.utils.spec_detector import SpecDetector, SpecType


class PRDSpecSplitter:
    """
    Splits multi-test specs (PRD, Native Plan, or Standard Multi) into individual test specs.

    Each test case becomes a standalone spec file
    that can be processed independently through the pipeline.
    """

    @classmethod
    def split_spec(
        cls, spec_path: Path, output_dir: Path | None = None, use_ai: bool = True, mode: str = "individual"
    ) -> tuple:
        """
        Split a multi-test spec into individual or grouped test spec files.

        Args:
            spec_path: Path to PRD, Native Plan, or Standard Multi spec
            output_dir: Directory to save individual specs (default: same directory as input)
            use_ai: Whether to use AI extraction (True = AI-first, False = regex only)
            mode: "individual" for one spec per TC, "grouped" for one spec per group

        Returns:
            Tuple of (generated_files: List[Path], groups: Optional[List[Dict]])
            groups is None if regex was used (no grouping info available)
        """
        # Verify it's a splittable spec
        spec_type = SpecDetector.detect_spec_type(spec_path)
        content = spec_path.read_text()

        # Accept PRD, NATIVE_PLAN, STANDARD_MULTI, or STANDARD with TC patterns
        is_splittable = spec_type in (SpecType.PRD, SpecType.NATIVE_PLAN, SpecType.STANDARD_MULTI)
        if not is_splittable:
            # Check if it has TC patterns even though type detection said STANDARD
            pattern_count = SpecDetector.count_test_patterns(content)
            if pattern_count < 2:
                raise ValueError(f"Spec is not a multi-test spec (detected type: {spec_type})")

        test_cases = []
        groups = None

        # 1. AI-first: Try AI extraction as primary method
        if use_ai:
            print("   Using AI extraction (primary)...")
            try:
                from orchestrator.utils.ai_spec_splitter import AISpecSplitter

                test_cases, groups = AISpecSplitter.extract_and_group(content, spec_path.name)
                print(f"   AI extracted {len(test_cases)} test cases in {len(groups or [])} groups")
            except ImportError:
                try:
                    from utils.ai_spec_splitter import AISpecSplitter

                    test_cases, groups = AISpecSplitter.extract_and_group(content, spec_path.name)
                    print(f"   AI extracted {len(test_cases)} test cases in {len(groups or [])} groups")
                except ImportError:
                    print("   Warning: AI spec splitter not available, falling back to regex")
            except RuntimeError as e:
                print(f"   AI extraction failed: {e}")
                print("   Falling back to regex extraction...")

        # 2. Regex fallback: If AI failed or was disabled
        if not test_cases:
            print("   Using regex extraction (fallback)...")
            test_cases = SpecDetector.extract_test_cases(spec_path)
            groups = None  # No grouping info from regex

        if not test_cases:
            print(f"No test cases found in {spec_path}")
            return [], None

        # Set output directory
        if output_dir is None:
            output_dir = spec_path.parent / f"{spec_path.stem}-tests"
        output_dir.mkdir(parents=True, exist_ok=True)

        generated_files = []

        # Read the original spec to get metadata
        shared_context = cls._extract_shared_context(content)
        app_overview = shared_context.get("Overview", shared_context.get("Application Overview", ""))
        shared_context_md = cls._format_shared_context_markdown(shared_context)

        # Extract base URL origin for resolving relative URLs in child specs
        base_url_origin = cls._extract_base_url_origin(content)

        # Grouped mode: create one spec per group
        if mode == "grouped" and groups:
            # Build lookup of test cases by ID
            tc_by_id = {tc["id"]: tc for tc in test_cases}

            for group in groups:
                group_tcs = [tc_by_id[tid] for tid in group.get("test_ids", []) if tid in tc_by_id]
                if not group_tcs:
                    continue

                spec_content = cls._create_grouped_spec(
                    group=group,
                    test_cases=group_tcs,
                    app_overview=app_overview,
                    source_spec=spec_path.name,
                    base_url_origin=base_url_origin,
                    shared_context=shared_context_md,
                )

                filename = cls._sanitize_filename(group.get("name", "group"))
                output_path = output_dir / f"{filename}.md"
                output_path.write_text(spec_content)
                generated_files.append(output_path)
                print(f"  {output_path.name} ({len(group_tcs)} tests)")

        else:
            # Individual mode: one spec per test case (default behavior)
            for test_case in test_cases:
                if test_case.get("_ai_extracted"):
                    spec_content = cls._create_rich_individual_spec(
                        test_case=test_case,
                        app_overview=app_overview,
                        source_spec=spec_path.name,
                        base_url_origin=base_url_origin,
                        shared_context=shared_context_md,
                    )
                else:
                    spec_content = cls._create_individual_spec(
                        test_case=test_case,
                        app_overview=app_overview,
                        source_spec=spec_path.name,
                        base_url_origin=base_url_origin,
                        shared_context=shared_context_md,
                    )

                filename = cls._sanitize_filename(f"{test_case['id']}-{test_case['name']}")
                output_path = output_dir / f"{filename}.md"
                output_path.write_text(spec_content)
                generated_files.append(output_path)
                print(f"  {output_path.name}")

        return generated_files, groups

    # Category names that contain test cases (these are NOT shared context)
    TEST_CATEGORY_NAMES = {
        "happy path",
        "edge cases",
        "edge case",
        "error",
        "validation",
        "performance",
        "accessibility",
        "integration",
        "security",
        "regression",
        "cross-browser",
        "boundary",
        "negative",
        "test cases",
        "test scenarios",
    }

    @classmethod
    def _find_test_category_sections(cls, lines: list) -> set:
        """
        Pre-scan lines to find ## section names that contain test case headers underneath.
        This detects arbitrary category names like "Service Access Tests" that have
        ### TC-XXX or ### Test X.X headers as children.
        """
        test_sections = set()
        current_h2 = None

        for line in lines:
            stripped = line.strip()

            # Track ## headings
            h2_match = re.match(r"^##\s+(.+)$", stripped)
            if h2_match and not stripped.startswith("### "):
                current_h2 = h2_match.group(1).strip()
                continue

            # If we see a TC pattern under current h2, mark it as test category
            if current_h2:
                # Check for TC-XXX, Test X.X, #### X.X. patterns
                if re.match(r"#{3,4}\s+\*{0,2}\s*(?:Test\s+)?(?:TC-\d+|\d+\.\d+)[:.]\s+", stripped):
                    test_sections.add(current_h2.lower())

        return test_sections

    @classmethod
    def _extract_app_overview(cls, content: str) -> str:
        """Extract the application overview section from PRD spec."""
        shared = cls._extract_shared_context(content)
        return shared.get("Overview", "")

    @classmethod
    def _extract_shared_context(cls, content: str) -> dict:
        """
        Extract all shared context sections from the spec.

        Walks the spec collecting ## sections that appear BEFORE the first
        test-case-containing section, plus trailing sections AFTER all test cases.

        Returns dict mapping section name to content, plus '_title' for the H1 title.
        """
        lines = content.split("\n")

        # Pre-scan to find sections containing test case headers
        dynamic_test_sections = cls._find_test_category_sections(lines)

        sections: dict = {}
        current_section = None
        current_lines: list = []
        title = ""
        in_test_section = False

        for line in lines:
            stripped = line.strip()

            # Capture H1 title
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = stripped
                continue

            # Detect ## section headers
            h2_match = re.match(r"^##\s+(.+)$", stripped)
            if h2_match:
                # Save previous section if it was shared context
                if current_section and not in_test_section:
                    sections[current_section] = "\n".join(current_lines).strip()

                section_name = h2_match.group(1).strip()

                # Check if this section contains test cases
                if cls._is_test_category_section(section_name, dynamic_test_sections):
                    in_test_section = True
                    current_section = None
                    current_lines = []
                else:
                    # This is a shared context section (before or after test cases)
                    in_test_section = False
                    current_section = section_name
                    current_lines = []
                continue

            # Collect lines for current section
            if current_section and not in_test_section:
                # Skip --- separators at the very start or end
                if stripped == "---":
                    continue
                current_lines.append(line)

        # Save last section if it was shared context
        if current_section and not in_test_section:
            sections[current_section] = "\n".join(current_lines).strip()

        sections["_title"] = title
        return sections

    # Section names that are shared context (NOT test categories), even if they contain "test"
    SHARED_SECTION_NAMES = {
        "test environment",
        "test data requirements",
        "test data",
        "test summary",
        "test setup",
        "test configuration",
        "test prerequisites",
        "overview",
        "application overview",
        "notes",
        "references",
        "key selectors discovered",
        "key selectors identified",
        "key selectors",
    }

    @classmethod
    def _is_test_category_section(cls, section_name: str, dynamic_sections: set = None) -> bool:
        """Check if a ## section name is a test category (contains test cases)."""
        name_lower = section_name.lower().strip()

        # Explicitly known shared context sections are NOT test categories
        if name_lower in cls.SHARED_SECTION_NAMES:
            return False

        # Check dynamic sections from pre-scan
        if dynamic_sections and name_lower in dynamic_sections:
            return True

        # Check for known test category keywords
        for cat in cls.TEST_CATEGORY_NAMES:
            if cat in name_lower:
                return True

        return False

    @classmethod
    def _format_shared_context_markdown(cls, shared_context: dict) -> str:
        """
        Format shared context dict into markdown for injection into split files.

        Renders in logical order, skipping Overview and _title (used separately).
        """
        output_parts = []

        # Priority order for shared sections
        priority_sections = [
            "Test Environment",
            "Key Selectors Discovered",
            "Key Selectors Identified",
            "Test Data Requirements",
            "Test Summary",
            "Notes",
            "References",
        ]

        rendered = set()
        for section_name in priority_sections:
            if section_name in shared_context and shared_context[section_name]:
                output_parts.append(f"## {section_name}\n{shared_context[section_name]}")
                rendered.add(section_name)

        # Render any remaining sections not in priority list (except Overview, _title)
        skip = {"Overview", "Application Overview", "_title"} | rendered
        for section_name, section_content in shared_context.items():
            if section_name not in skip and section_content:
                output_parts.append(f"## {section_name}\n{section_content}")

        return "\n\n".join(output_parts)

    @classmethod
    def _extract_base_url_origin(cls, content: str) -> str | None:
        """
        Extract the URL origin (scheme + host) from spec content.

        Looks for absolute URLs in overview sections and common URL patterns,
        returns just the origin (e.g., 'https://example.com') for resolving
        relative URLs in child specs.
        """
        # Try labeled URL patterns first
        patterns = [
            r"\*\*(?:Target |Application |Base |Entry )?URL\*?\*?:\s*(https?://\S+)",
            r"(?:Navigate to|Go to)\s+`?(https?://[^\s`]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                url = match.group(1).strip("`.,;:")
                from urllib.parse import urlparse

                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc:
                    return f"{parsed.scheme}://{parsed.netloc}"

        # Fallback: find any absolute URL
        abs_match = re.search(r"(https?://[^\s\)\"\'`>]+)", content)
        if abs_match:
            url = abs_match.group(1).rstrip(".,;:")
            from urllib.parse import urlparse

            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"

        return None

    @classmethod
    def _create_grouped_spec(
        cls,
        group: dict,
        test_cases: list[dict],
        app_overview: str,
        source_spec: str,
        base_url_origin: str | None = None,
        shared_context: str = "",
    ) -> str:
        """Create a combined spec file containing multiple related test cases."""
        group_name = group.get("name", "Test Group")
        group_desc = group.get("description", "")
        test_ids = [tc["id"] for tc in test_cases]

        spec = f"""# Test Group: {group_name}

## Source
Generated from: `{source_spec}`
Tests: {", ".join(test_ids)} ({len(test_cases)} test cases)

"""

        # Inject shared context
        if shared_context:
            spec += shared_context + "\n\n"

        # Add group description
        desc_text = group_desc or app_overview or f"Tests for {group_name}"
        spec += f"## Description\n{desc_text}\n\n"

        # Add each test case as a section
        for tc in test_cases:
            spec += f"---\n\n### {tc['id']}: {tc.get('name', 'Unnamed Test')}\n\n"

            # For AI-extracted tests, use structured data
            if tc.get("_ai_extracted"):
                description = tc.get("_description", "")
                if description:
                    spec += f"**Description**: {description}\n\n"

                preconditions = tc.get("_preconditions", [])
                if preconditions:
                    spec += "**Preconditions**:\n"
                    for pre in preconditions:
                        spec += f"- {pre}\n"
                    spec += "\n"

                steps = list(tc.get("_steps", []))
                url = tc.get("_url", "")

                # Resolve relative URL
                if url and url.startswith("/") and base_url_origin:
                    url = f"{base_url_origin}{url}"

                # Resolve relative URLs in steps
                if base_url_origin:
                    steps = cls._resolve_step_urls(steps, base_url_origin)

                # Add URL as first step if needed
                if url and steps and not any(url in s for s in steps):
                    if not any(s.lower().startswith("navigate") or s.lower().startswith("go to") for s in steps[:1]):
                        steps = [f"Navigate to {url}"] + steps

                if steps:
                    spec += "**Steps**:\n"
                    for i, step in enumerate(steps, 1):
                        spec += f"{i}. {step}\n"
                    spec += "\n"

                expected_results = tc.get("_expected_results", [])
                if expected_results:
                    spec += "**Expected Results**:\n"
                    for result in expected_results:
                        spec += f"- {result}\n"
                    spec += "\n"

                selectors = tc.get("_selectors", [])
                if selectors:
                    spec += "**Selector Hints**:\n"
                    for sel in selectors:
                        spec += f"- `{sel}`\n"
                    spec += "\n"

            else:
                # For regex-extracted tests, include raw content
                content = tc.get("content", "")
                if content:
                    spec += content + "\n\n"

        return spec

    @classmethod
    def _create_rich_individual_spec(
        cls,
        test_case: dict,
        app_overview: str,
        source_spec: str,
        base_url_origin: str | None = None,
        shared_context: str = "",
    ) -> str:
        """
        Create a standalone spec from AI-extracted structured data.

        Uses the structured fields directly (description, preconditions, steps,
        expected_results, selectors, url) instead of re-parsing the content string.
        """
        description = test_case.get("_description", "")
        preconditions = test_case.get("_preconditions", [])
        steps = list(test_case.get("_steps", []))
        expected_results = test_case.get("_expected_results", [])
        selectors = test_case.get("_selectors", [])
        url = test_case.get("_url", "")

        # Resolve relative URL against base URL origin
        if url and url.startswith("/") and base_url_origin:
            url = f"{base_url_origin}{url}"

        # Resolve relative URLs in steps
        if base_url_origin:
            steps = cls._resolve_step_urls(steps, base_url_origin)

        # Detect auth requirements
        requires_auth = cls._detect_auth_requirement(test_case, steps)
        is_auth_test = cls._is_authentication_test(test_case)

        # Use test-specific description, fall back to full overview (no truncation)
        desc_text = description or app_overview or f"Test for {test_case['name']}"

        # Build the spec
        spec = f"""# Test: {test_case["name"]}

## Source
Generated from: `{source_spec}`
Test ID: {test_case["id"]}
Category: {test_case["category"]}

"""

        # Inject shared context (Test Environment, etc.) right after Source
        if shared_context:
            spec += shared_context + "\n\n"

        # Add description
        spec += f"## Description\n{desc_text}\n\n"

        # Add preconditions section
        if test_case.get("seed"):
            spec += f"""## Preconditions
@include "{test_case["seed"]}"

"""
        elif preconditions:
            spec += "## Preconditions\n"
            for pre in preconditions:
                spec += f"- {pre}\n"
            spec += "\n"

            # Also add auth template if needed
            if requires_auth and not is_auth_test:
                has_login_pre = any("logged in" in p.lower() or "login" in p.lower() for p in preconditions)
                if not has_login_pre:
                    spec += '@include "templates/login.md"\n\n'
        elif requires_auth and not is_auth_test:
            spec += """## Preconditions
@include "templates/login.md"

"""

        # Add URL as first step if available and not already in steps
        if url and steps and not any(url in s for s in steps):
            # Check if first step already has a navigation
            if not any(s.lower().startswith("navigate") or s.lower().startswith("go to") for s in steps[:1]):
                steps = [f"Navigate to {url}"] + steps

        # Add steps
        spec += "## Steps\n\n"
        for i, step in enumerate(steps, 1):
            spec += f"{i}. {step}\n"

        # Add expected outcome
        if expected_results:
            spec += "\n## Expected Outcome\n\n"
            for result in expected_results:
                spec += f"- {result}\n"

        # Add selectors section if available
        if selectors:
            spec += "\n## Selector Hints\n\n"
            for sel in selectors:
                spec += f"- `{sel}`\n"

        # Add metadata comment
        if test_case.get("file_path"):
            spec += f"\n<!-- Suggested output: {test_case['file_path']} -->\n"

        return spec

    @classmethod
    def _create_individual_spec(
        cls,
        test_case: dict,
        app_overview: str,
        source_spec: str,
        base_url_origin: str | None = None,
        shared_context: str = "",
    ) -> str:
        """
        Create a standalone spec file for an individual test case.

        Converts PRD test case format to simple step-based format.
        Injects shared context (Test Environment, Notes, etc.) from parent spec.
        """
        # Parse description, preconditions, steps and expected results from content
        tc_description, tc_preconditions, steps, expected_results = cls._parse_test_case_content(test_case["content"])

        # Resolve relative URLs in steps
        if base_url_origin:
            steps = cls._resolve_step_urls(steps, base_url_origin)

        # Detect if this test requires authentication
        requires_auth = cls._detect_auth_requirement(test_case, steps)
        is_auth_test = cls._is_authentication_test(test_case)

        # Use test-specific description, fall back to overview
        description = tc_description or app_overview or f"Test for {test_case['name']}"

        # Build the spec
        spec = f"""# Test: {test_case["name"]}

## Source
Generated from: `{source_spec}`
Test ID: {test_case["id"]}
Category: {test_case["category"]}

"""

        # Inject shared context (Test Environment, etc.) right after Source
        if shared_context:
            spec += shared_context + "\n\n"

        # Add description
        spec += f"## Description\n{description}\n\n"

        # Add preconditions
        if test_case.get("seed"):
            spec += f"""## Preconditions
@include "{test_case["seed"]}"

"""
        elif tc_preconditions:
            spec += "## Preconditions\n"
            for pre in tc_preconditions:
                spec += f"- {pre}\n"
            spec += "\n"
            # Also add auth template if needed and not already implied
            if requires_auth and not is_auth_test:
                has_login_pre = any("logged in" in p.lower() or "login" in p.lower() for p in tc_preconditions)
                if not has_login_pre:
                    spec += '@include "templates/login.md"\n\n'
        elif requires_auth and not is_auth_test:
            spec += """## Preconditions
@include "templates/login.md"

"""

        # Add steps
        spec += "## Steps\n\n"
        for i, step in enumerate(steps, 1):
            spec += f"{i}. {step}\n"

        # Add expected outcome
        if expected_results:
            spec += "\n## Expected Outcome\n\n"
            for result in expected_results:
                spec += f"- {result}\n"

        # Add metadata comment
        if test_case.get("file_path"):
            spec += f"\n<!-- Suggested output: {test_case['file_path']} -->\n"

        return spec

    @classmethod
    def _resolve_step_urls(cls, steps: list[str], base_url_origin: str) -> list[str]:
        """
        Resolve relative URLs in step strings to absolute URLs.

        Handles patterns like:
        - "Navigate to /path" -> "Navigate to https://example.com/path"
        - "Go to `/path`" -> "Go to `https://example.com/path`"
        """
        resolved = []
        for step in steps:
            # Match "Navigate to /path" or "Go to /path" with optional backticks
            match = re.match(r"^(.*(?:Navigate to|Go to)\s+)`?(/[^\s`]*)`?(.*)$", step, re.IGNORECASE)
            if match:
                prefix, path, suffix = match.groups()
                resolved.append(f"{prefix}{base_url_origin}{path}{suffix}")
            else:
                resolved.append(step)
        return resolved

    @classmethod
    def _detect_auth_requirement(cls, test_case: dict, steps: list[str]) -> bool:
        """
        Detect if a test requires authentication based on URLs and content.
        """
        content = test_case.get("content", "").lower()
        steps_text = " ".join(steps).lower()

        # URLs that typically require authentication
        auth_required_patterns = [
            "/user/",
            "/users/",
            "/dashboard",
            "/admin",
            "/account",
            "/profile",
            "/settings",
            "/my_trips",
            "/my-trips",
            "/my_bookings",
            "/my-bookings",
            "/orders",
            "/checkout",
        ]

        # Check if any auth-required URL pattern is in the content or steps
        for pattern in auth_required_patterns:
            if pattern in content or pattern in steps_text:
                return True

        # Also check preconditions from AI extraction
        preconditions = test_case.get("_preconditions", [])
        for pre in preconditions:
            pre_lower = pre.lower()
            if "logged in" in pre_lower or "authenticated" in pre_lower or "login" in pre_lower:
                return True

        return False

    @classmethod
    def _is_authentication_test(cls, test_case: dict) -> bool:
        """
        Detect if a test is specifically testing authentication/login functionality.
        These tests should NOT include a login template as they ARE the login test.
        """
        name = test_case.get("name", "").lower()
        test_case.get("category", "").lower()
        content = test_case.get("content", "").lower()

        # Test names that indicate auth testing
        auth_test_keywords = [
            "login",
            "log in",
            "sign in",
            "signin",
            "authentication",
            "auth flow",
            "oauth",
            "sso",
            "password",
            "credential",
            "magic link",
            "email verification",
            "register",
            "signup",
            "sign up",
        ]

        for keyword in auth_test_keywords:
            if keyword in name:
                return True

        # Check if first step is navigating to login page
        if "navigate to" in content and any(p in content for p in ["/login", "/signin", "/sign-in", "/auth"]):
            # But only if the test is about the login flow itself
            if any(kw in name for kw in ["login", "auth", "sign"]):
                return True

        return False

    @classmethod
    def _parse_test_case_content(cls, content: str) -> tuple[str, list[str], list[str], list[str]]:
        """
        Parse description, preconditions, steps and expected results from test case content.

        Handles both PRD format (**Steps:**) and Explorer format (**Steps**:).

        Returns:
            Tuple of (description, preconditions_list, steps_list, expected_results_list)
        """
        description = ""
        preconditions = []
        steps = []
        expected_results = []

        lines = content.split("\n")
        in_description = False
        in_preconditions = False
        in_steps = False
        in_expected = False

        for line in lines:
            stripped = line.strip()

            # Detect sections - handle both formats:
            # PRD format: **Steps:** or **Expected Results:**
            # Explorer format: **Steps**: or **Expected Results**:
            is_description_header = stripped.startswith("**Description:**") or stripped.startswith("**Description**:")
            is_preconditions_header = (
                stripped.startswith("**Preconditions:**")
                or stripped.startswith("**Preconditions**:")
                or stripped.startswith("**Precondition:**")
                or stripped.startswith("**Precondition**:")
            )
            is_steps_header = (
                stripped.startswith("**Steps:**") or stripped.startswith("**Steps**:") or stripped == "**Steps**"
            )
            is_expected_header = (
                stripped.startswith("**Expected Results:**")
                or stripped.startswith("**Expected Result:**")
                or stripped.startswith("**Expected Results**:")
                or stripped.startswith("**Expected Result**:")
            )

            if is_description_header:
                in_description = True
                in_preconditions = False
                in_steps = False
                in_expected = False
                # Check for inline description: **Description**: Some text here
                inline = re.sub(r"^\*\*Description\*?\*?:\s*", "", stripped)
                if inline:
                    description = inline
                continue
            elif is_preconditions_header:
                in_description = False
                in_preconditions = True
                in_steps = False
                in_expected = False
                # Check for inline single precondition
                inline = re.sub(r"^\*\*Preconditions?\*?\*?:\s*", "", stripped)
                if inline and not inline.startswith("-"):
                    preconditions.append(inline)
                continue
            elif is_steps_header:
                in_description = False
                in_preconditions = False
                in_steps = True
                in_expected = False
                continue
            elif is_expected_header:
                in_description = False
                in_preconditions = False
                in_steps = False
                in_expected = True
                continue
            elif stripped.startswith("**") and ":" in stripped:
                # Another section started (e.g., **File**: or **Seed**:)
                in_description = False
                in_preconditions = False
                in_steps = False
                in_expected = False
                continue
            elif stripped.startswith("##") or stripped.startswith("---"):
                # New section or separator
                in_description = False
                in_preconditions = False
                in_steps = False
                in_expected = False
                continue

            # Extract content
            if in_description and stripped:
                if description:
                    description += " " + stripped
                else:
                    description = stripped

            if in_preconditions and stripped:
                if stripped.startswith("-") or stripped.startswith("*"):
                    preconditions.append(stripped[1:].strip())
                elif stripped:
                    preconditions.append(stripped)

            if in_steps and stripped:
                # Match numbered steps
                step_match = re.match(r"^\d+\.\s+(.+)$", stripped)
                if step_match:
                    step_text = step_match.group(1)
                    steps.append(step_text)
                elif steps and (stripped.startswith("-") or stripped.startswith("*")):
                    # Sub-item of previous step - append to last step
                    sub_text = stripped[1:].strip()
                    steps[-1] += f" | {sub_text}"

            if in_expected and stripped:
                # Remove list markers
                if stripped.startswith("-") or stripped.startswith("*"):
                    result_text = stripped[1:].strip()
                    expected_results.append(result_text)

        return description, preconditions, steps, expected_results

    @classmethod
    def _sanitize_filename(cls, name: str) -> str:
        """Convert test name to valid filename."""
        # Remove special characters
        name = re.sub(r"[^\w\s-]", "", name)
        # Replace spaces with hyphens
        name = re.sub(r"[\s_]+", "-", name)
        # Convert to lowercase
        name = name.lower()
        # Limit length
        if len(name) > 60:
            name = name[:60]
        return name.strip("-")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Split PRD spec into individual test specs")
    parser.add_argument("spec", help="Path to PRD spec file")
    parser.add_argument("--output-dir", "-o", help="Output directory (default: <spec-name>-tests/)")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI extraction (use regex only)")
    parser.add_argument(
        "--mode",
        choices=["individual", "grouped"],
        default="individual",
        help="Split mode: individual (one spec per TC) or grouped (one spec per group)",
    )

    args = parser.parse_args()

    prd_spec = Path(args.spec)
    if not prd_spec.exists():
        print(f"File not found: {prd_spec}")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None

    print(f"Splitting {prd_spec.name} (mode={args.mode})...")
    files, groups = PRDSpecSplitter.split_spec(prd_spec, output_dir, use_ai=not args.no_ai, mode=args.mode)
    print(f"\nCreated {len(files)} spec files")
    if groups:
        print(f"   Groups: {len(groups)}")
        for g in groups:
            print(f"     - {g.get('name', '?')}: {len(g.get('test_ids', []))} tests")
    if files:
        print(f"   Output: {files[0].parent}")

"""
Spec Detector - Determines the type and format of test specifications
"""

import re
from pathlib import Path


class SpecType:
    """Types of test specifications"""

    STANDARD = "standard"  # Simple markdown format for standard pipeline
    PRD = "prd"  # PRD-generated multi-test format for native pipeline
    NATIVE_PLAN = "native_plan"  # Native planner generated multi-test format
    TEMPLATE = "template"  # Reusable template spec
    STANDARD_MULTI = "standard_multi"  # Multiple # Test: sections at H1 level
    API = "api"  # API-only test spec using Playwright request fixture
    MIXED = "mixed"  # Mixed browser + API test spec


class SpecDetector:
    """
    Detects the type and structure of test specifications.

    PRD/Native Plan specs are identified by:
    - Multiple test cases with **File:** metadata
    - Complex structure with test suites/scenarios
    - Actions not in standard schema (hover, drag, etc.)
    - Path: specs/<project-name>/*.md (from PRD generation)
    """

    # Patterns for API-only specs
    API_PATTERNS = [
        r"##\s+Type:\s*API",  # Explicit API type declaration
        r"##\s+API\s+Steps",  # API steps section
        r"##\s+Base\s+URL:",  # Base URL declaration (inline)
        r"##\s+Auth:",  # Auth header declaration
        r"#\s+API\s+Spec:",  # Exploration-generated API spec title
        r"##\s+Endpoints",  # Endpoints section header
    ]

    # Patterns for mixed browser + API specs
    MIXED_STEP_PATTERN = r"^\s*\d+\.\s+\[API\]\s+"  # Steps prefixed with [API]

    PRD_PATTERNS = [
        r"\*\*File\*?\*?:\*?\*?\s*`tests/generated/",  # File path metadata (handles **File**: and **File**)
        r"### \d+\.\s+(Happy Path|Edge Cases|Error Scenarios|Accessibility)",  # Test categories
        r"### Suite \d+:\s+(Happy Path|Edge Cases|Error|Accessibility)",  # Explorer format categories
        r"\*\*Seed\*?\*?:\*?\*?\s*`",  # Seed reference (more flexible)
        r"#### \d+\.\d+\.",  # Numbered test cases (PRD format)
        r"#### Test \d+\.\d+:",  # Numbered test cases (Explorer format)
    ]

    # Patterns for native planner generated specs
    NATIVE_PLAN_PATTERNS = [
        r"## Test Suite \d+:\s+",  # Test suite header (native planner format)
        r"## Suite \d+:\s+",  # Suite header (autonomous agent format - without "Test" prefix)
        r"### Test \d+\.\d+:\s+",  # Test case header (native planner format)
        r"### \*{0,2}Test TC-\d+:\s+",  # Test case header (autonomous agent format - TC-XXX with "Test" prefix)
        r"### \*{0,2}TC-\d+:\s+",  # Test case header (TC-XXX without "Test" prefix, optional bold)
        r"####\s+\*{0,2}TC-\d+:\s+",  # TC-XXX at heading level 4 (some autonomous agents use this, optional bold)
        r"\*\*File\*?\*?:\s*`tests/",  # File path metadata
        r"\*\*Steps\*?\*?:",  # Steps section
        r"\*\*Expected Results?\*?\*?:",  # Expected results section (singular or plural)
        r"# Test Plan:",  # Test plan header
        r"## Overview",  # Overview section
        r"## Test Cases",  # Common section header for test cases
        r"### Key Selectors Discovered",  # Selectors section (native planner)
        r"## Key Selectors Discovered",  # Selectors section (autonomous agent - ## level)
        r"#{2,3}\s+(?:Happy Path|Edge Cases?|Error|Validation|Performance|Accessibility|Integration|Security|Regression|Cross-Browser)\s",  # Named categories at ## or ### level
    ]

    STANDARD_ACTIONS = {"navigate", "click", "fill", "select", "check", "uncheck", "wait", "assert", "screenshot"}

    @classmethod
    def detect_spec_type(cls, spec_path: Path) -> str:
        """
        Detect the type of spec file.

        Returns:
            SpecType constant (STANDARD, PRD, NATIVE_PLAN, or TEMPLATE)
        """
        if not spec_path.exists():
            raise FileNotFoundError(f"Spec not found: {spec_path}")

        content = spec_path.read_text()

        # Check if it's a template (in templates/ directory)
        if "templates" in spec_path.parts:
            return SpecType.TEMPLATE

        # Check for API spec type (highest priority for explicit declarations)
        api_matches = sum(1 for pattern in cls.API_PATTERNS if re.search(pattern, content, re.IGNORECASE))
        if api_matches >= 2:
            return SpecType.API

        # Check for mixed browser + API specs
        mixed_steps = re.findall(cls.MIXED_STEP_PATTERN, content, re.MULTILINE)
        if mixed_steps:
            # Has [API] prefixed steps - check if there are also browser steps
            all_steps = re.findall(r"^\s*\d+\.\s+", content, re.MULTILINE)
            browser_steps = len(all_steps) - len(mixed_steps)
            if browser_steps > 0:
                return SpecType.MIXED
            elif api_matches >= 1:
                # All steps are [API] with at least one API pattern
                return SpecType.API

        # Check for native planner patterns first (more specific)
        native_plan_matches = sum(1 for pattern in cls.NATIVE_PLAN_PATTERNS if re.search(pattern, content))

        # If 3 or more native plan patterns match, it's a native planner spec
        if native_plan_matches >= 3:
            return SpecType.NATIVE_PLAN

        # Check for PRD patterns
        prd_matches = sum(1 for pattern in cls.PRD_PATTERNS if re.search(pattern, content))

        # If 2 or more PRD patterns match, it's a PRD spec
        if prd_matches >= 2:
            return SpecType.PRD

        # Check for actions not in standard schema
        non_standard_actions = cls._find_non_standard_actions(content)
        if non_standard_actions and prd_matches >= 1:
            return SpecType.PRD

        # Check for Standard Multi-Test format (multiple # Test: headers at H1 level)
        test_headers = re.findall(r"^# Test:\s+", content, re.MULTILINE)
        if len(test_headers) > 1:
            return SpecType.STANDARD_MULTI

        return SpecType.STANDARD

    @classmethod
    def is_multi_test_spec(cls, spec_path: Path) -> bool:
        """
        Check if spec contains multiple test cases (splittable).

        Returns True for PRD, NATIVE_PLAN, and STANDARD_MULTI specs,
        or for STANDARD specs that contain 2+ TC-pattern matches.
        """
        spec_type = cls.detect_spec_type(spec_path)
        if spec_type in (SpecType.PRD, SpecType.NATIVE_PLAN, SpecType.STANDARD_MULTI):
            return True

        # Fallback: if regex-based detection says STANDARD but content has TC patterns
        if spec_type == SpecType.STANDARD:
            content = spec_path.read_text()
            if cls.count_test_patterns(content) >= 2:
                return True

        return False

    @classmethod
    def count_test_patterns(cls, content: str) -> int:
        """
        Count unique test case patterns in content at any heading level.

        Counts TC-NNN, Test X.X, numbered test cases, etc.
        Used as a fallback heuristic for UI badges when extract_test_cases() returns 0.
        """
        found_ids = set()

        # TC-NNN at any heading level (####, ###, ##) - handles optional **bold** markers
        for match in re.finditer(r"#{2,4}\s+\*{0,2}\s*(?:Test\s+)?TC-(\d+)", content):
            found_ids.add(f"TC-{match.group(1)}")

        # Numbered test cases: Test X.X or X.X.
        for match in re.finditer(r"#{2,4}\s+(?:Test\s+)?(\d+\.\d+)[:.]\s+", content):
            found_ids.add(match.group(1))

        return len(found_ids)

    @classmethod
    def _find_non_standard_actions(cls, content: str) -> list[str]:
        """Find actions that aren't in the standard schema."""
        # Look for common step patterns
        step_pattern = r"\d+\.\s+([A-Z][a-z]+)\s+"
        found_actions = re.findall(step_pattern, content)

        non_standard = []
        for action in found_actions:
            action_lower = action.lower()
            if action_lower not in cls.STANDARD_ACTIONS:
                # Common non-standard actions
                if action_lower in ["hover", "drag", "scroll", "focus", "blur", "type"]:
                    non_standard.append(action_lower)

        return non_standard

    @classmethod
    def extract_test_cases(cls, spec_path: Path) -> list[dict]:
        """
        Extract individual test cases from a PRD, Native Plan, or Standard Multi spec.

        Returns:
            List of test case dicts with:
            - id: Test case ID (e.g., "1.1", "TC-001")
            - name: Test case name
            - file_path: Suggested output file path
            - content: Test case content
            - category: Test category (Happy Path, Edge Cases, etc.)
            - seed: Optional seed file for setup
        """
        spec_type = cls.detect_spec_type(spec_path)
        if spec_type not in (SpecType.PRD, SpecType.NATIVE_PLAN, SpecType.STANDARD_MULTI):
            return []

        content = spec_path.read_text()

        # Use appropriate extraction method based on spec type
        if spec_type == SpecType.STANDARD_MULTI:
            return cls._extract_standard_multi_cases(content)
        elif spec_type == SpecType.NATIVE_PLAN:
            test_cases = cls._extract_native_plan_cases(content)
            # Fallback to PRD extraction if native plan extraction found nothing
            # This handles specs that are detected as native_plan but use PRD-style headers
            if not test_cases:
                test_cases = cls._extract_prd_cases(content)
            return test_cases
        else:
            return cls._extract_prd_cases(content)

    @classmethod
    def _extract_prd_cases(cls, content: str) -> list[dict]:
        """Extract test cases from PRD format specs."""
        test_cases = []

        # Parse test categories and cases
        current_category = None
        current_category_seed = None  # Track seed at category level
        current_case = None
        lines = content.split("\n")

        for _i, line in enumerate(lines):
            # Match category headers: ### 1. Happy Path Tests OR ### Suite 1: Happy Path Tests
            category_match = re.match(r"###\s+(?:\d+\.\s+|Suite \d+:\s+)(.+)", line)
            if category_match:
                # Save previous case if exists before starting new category
                if current_case:
                    test_cases.append(current_case)
                    current_case = None

                current_category = category_match.group(1).strip()
                current_category_seed = None  # Reset seed for new category
                continue

            # Catch-all: Any ### heading not already matched = category boundary
            # This handles arbitrary category names like "Service Access Tests"
            if line.startswith("### ") and not line.startswith("#### "):
                h3_match = re.match(r"^###\s+(.+)$", line)
                if h3_match:
                    section_name = h3_match.group(1).strip()
                    # Skip if it looks like a test case header (has numbered ID)
                    if not re.match(r"(?:Test\s+)?\d+\.\d+[:.]\s+", section_name):
                        if section_name.lower() not in {
                            "overview",
                            "application overview",
                            "test environment",
                            "test data requirements",
                            "test data",
                            "test summary",
                            "test setup",
                            "test configuration",
                            "test prerequisites",
                            "notes",
                            "references",
                            "key selectors discovered",
                            "key selectors identified",
                            "key selectors",
                        }:
                            if current_case:
                                test_cases.append(current_case)
                                current_case = None
                            current_category = section_name
                            current_category_seed = None
                            continue

            # Extract seed reference at category level (before any test cases)
            if line.strip().startswith("**Seed:**") and not current_case:
                seed_match = re.search(r"`(.+?)`", line)
                if seed_match:
                    current_category_seed = seed_match.group(1)
                continue

            # Match test case headers: #### 1.1. Test Name OR #### Test 1.1: Test Name
            case_match = re.match(r"####\s+(?:Test\s+)?(\d+\.\d+)[:.]\s+(.+)", line)
            if case_match:
                # Save previous case if exists
                if current_case:
                    test_cases.append(current_case)

                # Start new case, inherit category seed
                test_id = case_match.group(1)
                test_name = case_match.group(2).strip()
                current_case = {
                    "id": test_id,
                    "name": test_name,
                    "category": current_category or "Uncategorized",
                    "file_path": None,
                    "content": [line],
                    "seed": current_category_seed,  # Inherit from category
                }
                continue

            # Extract file path metadata
            if current_case and line.strip().startswith("**File:**"):
                file_match = re.search(r"`(.+?)`", line)
                if file_match:
                    current_case["file_path"] = file_match.group(1)

            # Extract seed reference (test case level override)
            if current_case and line.strip().startswith("**Seed:**"):
                seed_match = re.search(r"`(.+?)`", line)
                if seed_match:
                    current_case["seed"] = seed_match.group(1)  # Override category seed

            # Collect content until next case or category
            if current_case:
                current_case["content"].append(line)

        # Don't forget the last case
        if current_case:
            test_cases.append(current_case)

        # Convert content arrays to strings
        for case in test_cases:
            case["content"] = "\n".join(case["content"])

        return test_cases

    @classmethod
    def _extract_native_plan_cases(cls, content: str) -> list[dict]:
        """Extract test cases from Native Planner format specs."""
        test_cases = []

        # Parse test suites and cases (native planner uses ## for suites, ### for cases)
        current_category = None
        current_category_seed = None
        current_case = None
        lines = content.split("\n")

        for _i, line in enumerate(lines):
            # Match suite headers: ## Test Suite 1: Happy Path Tests OR ## Suite 1: Happy Path Tests
            suite_match = re.match(r"##\s+(?:Test )?Suite \d+:\s+(.+)", line)
            if suite_match:
                # Save previous case if exists before starting new suite
                if current_case:
                    test_cases.append(current_case)
                    current_case = None

                current_category = suite_match.group(1).strip()
                current_category_seed = None  # Reset seed for new suite
                continue

            # Match named category headers at ### or ## level:
            # ### Happy Path Tests, ## Edge Cases, ## Error Scenario Tests, etc.
            named_cat_match = re.match(
                r"#{2,3}\s+(Happy Path|Edge Cases?|Error|Validation|Performance|Accessibility|Negative|Boundary|Integration|Security|Regression|Cross-Browser)\s*(.*)",
                line,
            )
            if named_cat_match:
                if current_case:
                    test_cases.append(current_case)
                    current_case = None

                current_category = (named_cat_match.group(1) + " " + named_cat_match.group(2)).strip()
                current_category_seed = None
                continue

            # Catch-all: Any ## heading not already matched = category boundary
            # This handles arbitrary category names like "Service Access Tests"
            if line.startswith("## ") and not line.startswith("### "):
                h2_match = re.match(r"^##\s+(.+)$", line)
                if h2_match:
                    # Skip known shared-context sections
                    section_name = h2_match.group(1).strip()
                    if section_name.lower() not in {
                        "overview",
                        "application overview",
                        "test environment",
                        "test data requirements",
                        "test data",
                        "test summary",
                        "test setup",
                        "test configuration",
                        "test prerequisites",
                        "notes",
                        "references",
                        "key selectors discovered",
                        "key selectors identified",
                        "key selectors",
                    }:
                        if current_case:
                            test_cases.append(current_case)
                            current_case = None
                        current_category = section_name
                        current_category_seed = None
                        continue

            # Extract seed reference at suite level
            seed_match_line = re.match(r"\*\*Seed\*?\*?:\s*`(.+?)`", line.strip())
            if seed_match_line and not current_case:
                current_category_seed = seed_match_line.group(1)
                continue

            # Match test case headers: ### Test 1.1: Test Name
            case_match = re.match(r"###\s+Test\s+(\d+\.\d+):\s+(.+)", line)
            if case_match:
                # Save previous case if exists
                if current_case:
                    test_cases.append(current_case)

                # Start new case, inherit category seed
                test_id = case_match.group(1)
                test_name = case_match.group(2).strip()
                current_case = {
                    "id": test_id,
                    "name": test_name,
                    "category": current_category or "Uncategorized",
                    "file_path": None,
                    "content": [line],
                    "seed": current_category_seed,
                }
                continue

            # Also check for simpler format: ### Test 1.1. Test Name (with period)
            case_match_alt = re.match(r"###\s+Test\s+(\d+\.\d+)\.\s+(.+)", line)
            if case_match_alt:
                if current_case:
                    test_cases.append(current_case)

                test_id = case_match_alt.group(1)
                test_name = case_match_alt.group(2).strip()
                current_case = {
                    "id": test_id,
                    "name": test_name,
                    "category": current_category or "Uncategorized",
                    "file_path": None,
                    "content": [line],
                    "seed": current_category_seed,
                }
                continue

            # Also check for TC-XXX format: ### Test TC-001: Test Name OR ### TC-001: OR #### TC-001:
            # Handles optional **bold** markers: ### **TC-001: Name**
            tc_match = re.match(r"#{3,4}\s+\*{0,2}\s*(?:Test\s+)?TC-(\d+):\s+(.+?)\*{0,2}\s*$", line)
            if tc_match:
                if current_case:
                    test_cases.append(current_case)

                test_id = tc_match.group(1)
                test_name = tc_match.group(2).strip()
                current_case = {
                    "id": f"TC-{test_id}",
                    "name": test_name,
                    "category": current_category or "Uncategorized",
                    "file_path": None,
                    "content": [line],
                    "seed": current_category_seed,
                }
                continue

            # Extract file path metadata
            if current_case and re.match(r"\*\*File\*?\*?:", line.strip()):
                file_match = re.search(r"`(.+?)`", line)
                if file_match:
                    current_case["file_path"] = file_match.group(1)

            # Extract seed reference (test case level override)
            if current_case and re.match(r"\*\*Seed\*?\*?:", line.strip()):
                seed_match = re.search(r"`(.+?)`", line)
                if seed_match:
                    current_case["seed"] = seed_match.group(1)

            # Collect content until next case or suite
            if current_case:
                current_case["content"].append(line)

        # Don't forget the last case
        if current_case:
            test_cases.append(current_case)

        # Convert content arrays to strings
        for case in test_cases:
            case["content"] = "\n".join(case["content"])

        return test_cases

    @classmethod
    def _extract_standard_multi_cases(cls, content: str) -> list[dict]:
        """
        Extract test cases from Standard Multi-Test format.

        Format: Multiple # Test: headers with ## Source, ## Steps, ## Expected Outcome
        Example:
            # Test: Navigate to Service Categories Page

            ## Source
            Generated from: `browse-service-categories.md`
            Test ID: TC-001
            Category: Happy Path Tests

            ## Steps
            1. Step text

            ## Expected Outcome
            - Result
        """
        test_cases = []

        # Split by # Test: headers (but keep the header in each section)
        test_sections = re.split(r"(?=^# Test:\s+)", content, flags=re.MULTILINE)

        for section in test_sections:
            if not section.strip() or not section.startswith("# Test:"):
                continue

            # Extract test name from # Test: header
            name_match = re.match(r"^# Test:\s+(.+?)$", section, re.MULTILINE)
            if not name_match:
                continue
            test_name = name_match.group(1).strip()

            # Extract Test ID from ## Source section
            id_match = re.search(r"^Test ID:\s+(.+?)$", section, re.MULTILINE)
            test_id = id_match.group(1).strip() if id_match else "unknown"

            # Extract Category from ## Source section
            cat_match = re.search(r"^Category:\s+(.+?)$", section, re.MULTILINE)
            category = cat_match.group(1).strip() if cat_match else "Uncategorized"

            # Extract seed from @include if present in Steps
            seed_match = re.search(r'@include\s+"([^"]+)"', section)
            seed = seed_match.group(1) if seed_match else None

            # Extract file path if specified
            file_match = re.search(r"\*\*File\*?\*?:\s*`(.+?)`", section)
            file_path = file_match.group(1) if file_match else None

            test_cases.append(
                {
                    "id": test_id,
                    "name": test_name,
                    "category": category,
                    "file_path": file_path,
                    "content": section.strip(),
                    "seed": seed,
                }
            )

        return test_cases

    @classmethod
    def should_use_native_pipeline(cls, spec_path: Path) -> bool:
        """
        Determine if spec should use Native pipeline instead of Standard.

        Returns True for PRD and NATIVE_PLAN specs, False for Standard specs.
        """
        spec_type = cls.detect_spec_type(spec_path)
        return spec_type in (SpecType.PRD, SpecType.NATIVE_PLAN)

    @classmethod
    def get_spec_info(cls, spec_path: Path) -> dict:
        """
        Get comprehensive information about a spec file.

        Returns:
            Dict with spec type, test count, categories, etc.
        """
        spec_type = cls.detect_spec_type(spec_path)

        info = {
            "path": str(spec_path),
            "type": spec_type,
            "name": spec_path.stem,
            "test_count": 0,
            "categories": [],
            "test_cases": [],
        }

        if spec_type in (SpecType.PRD, SpecType.NATIVE_PLAN, SpecType.STANDARD_MULTI):
            test_cases = cls.extract_test_cases(spec_path)
            info["test_count"] = len(test_cases)
            info["categories"] = list(set(tc["category"] for tc in test_cases))
            info["test_cases"] = test_cases

            # Fallback: if regex extraction found nothing, use pattern counting for badge
            if info["test_count"] == 0:
                content = spec_path.read_text()
                pattern_count = cls.count_test_patterns(content)
                if pattern_count > 0:
                    info["test_count"] = pattern_count
        else:
            # For standard specs, check if it actually has multiple TC patterns
            content = spec_path.read_text()
            pattern_count = cls.count_test_patterns(content)
            info["test_count"] = max(1, pattern_count)

        return info


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python spec_detector.py <spec_path>")
        sys.exit(1)

    spec_path = Path(sys.argv[1])
    info = SpecDetector.get_spec_info(spec_path)

    print(f"Spec Type: {info['type']}")
    print(f"Test Count: {info['test_count']}")
    if info["categories"]:
        print(f"Categories: {', '.join(info['categories'])}")
    if info["test_cases"]:
        print("\nTest Cases:")
        for tc in info["test_cases"]:
            print(f"  {tc['id']}. {tc['name']} ({tc['category']})")
            if tc["seed"]:
                print(f"      Seed: {tc['seed']}")
            if tc["file_path"]:
                print(f"      → {tc['file_path']}")

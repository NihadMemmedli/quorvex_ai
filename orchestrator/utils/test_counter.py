"""
Utility functions for counting tests in Playwright test files.

This module provides functions to count individual test() blocks in .spec.ts files,
enabling accurate test counting when test files contain multiple tests.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def count_tests_in_file(file_path: str) -> int:
    """
    Count the number of test() blocks in a Playwright test file.

    This function parses .spec.ts files and counts individual test declarations.
    Handles various test patterns including:
    - test('name', ...)
    - test("name", ...)
    - test.only('name', ...)
    - test.skip('name', ...)
    - test.describe blocks (counted as containers, not tests themselves)

    Args:
        file_path: Path to the .spec.ts file

    Returns:
        Number of individual tests in the file. Returns 1 if file cannot be parsed
        (conservative estimate for single-test files).
    """
    try:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"Test file not found: {file_path}")
            return 1

        if path.suffix not in (".ts", ".js", ".mjs"):
            return 1

        content = path.read_text(encoding="utf-8")

        # Pattern to match test declarations:
        # - test('name', ...) or test("name", ...)
        # - test.only('name', ...) or test.only("name", ...)
        # - test.skip('name', ...) or test.skip("name", ...)
        # - test.fixme('name', ...) or test.fixme("name", ...)
        # Excludes test.describe, test.beforeEach, test.afterEach, etc.

        # Match: test followed by optional .only/.skip/.fixme, then ( and quote
        test_pattern = r'\btest(?:\.only|\.skip|\.fixme)?\s*\(\s*[\'"`]'

        matches = re.findall(test_pattern, content)
        count = len(matches)

        # If no tests found, return 1 as minimum (file might have different pattern)
        return max(1, count)

    except Exception as e:
        logger.warning(f"Error counting tests in {file_path}: {e}")
        return 1


def count_tests_in_directory(dir_path: str, pattern: str = "**/*.spec.ts") -> dict[str, int]:
    """
    Count tests in all matching files in a directory.

    Args:
        dir_path: Path to the directory to scan
        pattern: Glob pattern for test files

    Returns:
        Dictionary mapping file paths to test counts
    """
    result = {}
    path = Path(dir_path)

    if not path.exists():
        return result

    for test_file in path.glob(pattern):
        count = count_tests_in_file(str(test_file))
        result[str(test_file)] = count

    return result


def get_total_test_count(dir_path: str, pattern: str = "**/*.spec.ts") -> tuple[int, int]:
    """
    Get total test count and file count for a directory.

    Args:
        dir_path: Path to the directory to scan
        pattern: Glob pattern for test files

    Returns:
        Tuple of (total_tests, total_files)
    """
    counts = count_tests_in_directory(dir_path, pattern)
    total_tests = sum(counts.values())
    total_files = len(counts)
    return total_tests, total_files


def get_test_count_for_spec(spec_name: str, tests_dir: str = "tests/generated") -> int:
    """
    Get the test count for a specific spec file.

    Maps a spec name (e.g., "my-test.md") to its generated test file
    and counts the tests inside.

    Args:
        spec_name: Name of the spec file (with or without .md extension)
        tests_dir: Directory containing generated test files

    Returns:
        Number of tests in the generated file, or 1 if not found
    """
    # Normalize spec name - remove .md extension if present
    base_name = spec_name
    if base_name.endswith(".md"):
        base_name = base_name[:-3]

    # Replace slashes and convert to expected test file name
    test_name = base_name.replace("/", "_").replace("\\", "_")

    # Try various possible test file names
    tests_path = Path(tests_dir)
    possible_names = [
        f"{test_name}.spec.ts",
        f"{test_name.replace('-', '_')}.spec.ts",
        f"{test_name.replace('_', '-')}.spec.ts",
    ]

    for name in possible_names:
        test_file = tests_path / name
        if test_file.exists():
            return count_tests_in_file(str(test_file))

    # Try glob matching
    for test_file in tests_path.glob(f"*{test_name}*.spec.ts"):
        return count_tests_in_file(str(test_file))

    # Default to 1 if no matching file found
    return 1


def get_project_test_count(
    project_id: str, tests_dir: str = "tests/generated", specs_dir: str = "specs", session=None
) -> tuple[int, int]:
    """
    Get total test count for a specific project.

    Maps project's specs to their generated test files and counts tests.
    For 'default' project, includes specs with NULL project_id.

    Args:
        project_id: Project ID to filter by
        tests_dir: Directory containing generated test files
        specs_dir: Directory containing spec files
        session: SQLModel database session

    Returns:
        Tuple of (total_tests, total_files)
    """
    if session is None:
        return 0, 0

    # Import model here to avoid circular imports
    import sys

    from sqlalchemy import or_
    from sqlmodel import select

    if "orchestrator.api.models_db" in sys.modules:
        SpecMetadata = sys.modules["orchestrator.api.models_db"].SpecMetadata
    else:
        from orchestrator.api.models_db import SpecMetadata

    tests_path = Path(tests_dir)
    specs_path = Path(specs_dir)

    if not tests_path.exists():
        return 0, 0

    # Get specs for this project
    if project_id == "default":
        # Default project: include NULL and "default" project_id
        query = select(SpecMetadata.spec_name).where(
            or_(SpecMetadata.project_id == project_id, SpecMetadata.project_id == None)
        )
        db_spec_names = set(session.exec(query).all())

        # Also include filesystem specs not assigned to other projects
        other_projects_query = select(SpecMetadata.spec_name).where(
            SpecMetadata.project_id != "default", SpecMetadata.project_id != None
        )
        other_project_specs = set(session.exec(other_projects_query).all())

        for spec_file in specs_path.glob("**/*.md"):
            spec_name = str(spec_file.relative_to(specs_path))
            if spec_name not in other_project_specs:
                db_spec_names.add(spec_name)

        spec_names = db_spec_names
    else:
        # Other projects: only explicitly assigned specs
        query = select(SpecMetadata.spec_name).where(SpecMetadata.project_id == project_id)
        spec_names = set(session.exec(query).all())

    # Map specs to test files and count
    total_tests = 0
    total_files = 0

    for spec_name in spec_names:
        # Check if test file actually exists before counting
        test_file = _find_test_file_for_spec(spec_name, tests_dir)
        if test_file:
            total_files += 1
            total_tests += count_tests_in_file(str(test_file))

    return total_tests, total_files


def _find_test_file_for_spec(spec_name: str, tests_dir: str = "tests/generated") -> Path | None:
    """Helper to find the test file for a spec, returns None if not found.

    Handles various spec path formats:
    - Simple: "my-test.md" -> "my-test.spec.ts"
    - Nested: "folder/subfolder/my-test.md" -> "my-test.spec.ts" (filename-only match first)
    - Full path: "folder/subfolder/my-test.md" -> "folder_subfolder_my-test.spec.ts"
    """
    base_name = spec_name
    if base_name.endswith(".md"):
        base_name = base_name[:-3]

    # Extract just the filename (without directory path) - most common match pattern
    filename_only = Path(base_name).name
    # Also prepare the full path with underscores for flat structure
    full_path_underscored = base_name.replace("/", "_").replace("\\", "_")

    tests_path = Path(tests_dir)

    possible_names = [
        # First try filename only (most common pattern for nested specs)
        f"{filename_only}.spec.ts",
        f"{filename_only.replace('-', '_')}.spec.ts",
        f"{filename_only.replace('_', '-')}.spec.ts",
        # Then try full path with underscores
        f"{full_path_underscored}.spec.ts",
        f"{full_path_underscored.replace('-', '_')}.spec.ts",
        f"{full_path_underscored.replace('_', '-')}.spec.ts",
    ]

    for name in possible_names:
        test_file = tests_path / name
        if test_file.exists():
            return test_file

    # Try glob matching with filename only
    for test_file in tests_path.glob(f"*{filename_only}*.spec.ts"):
        return test_file

    # Try glob matching with full path
    if filename_only != full_path_underscored:
        for test_file in tests_path.glob(f"*{full_path_underscored}*.spec.ts"):
            return test_file

    return None


def get_tests_summary(tests_dir: str = "tests/generated") -> dict:
    """
    Get a summary of all tests in the generated tests directory.

    Returns:
        Dictionary with:
        - total_tests: Total number of individual tests
        - total_files: Total number of test files
        - files_with_multiple_tests: Files containing more than one test
        - breakdown: List of (file_name, test_count) tuples
    """
    counts = count_tests_in_directory(tests_dir)

    files_with_multiple = {name: count for name, count in counts.items() if count > 1}

    return {
        "total_tests": sum(counts.values()),
        "total_files": len(counts),
        "files_with_multiple_tests": len(files_with_multiple),
        "breakdown": sorted(counts.items(), key=lambda x: x[1], reverse=True),
    }

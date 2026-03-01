"""
Spec Parser - Converts markdown test specs into structured data for export.

Handles all spec formats: standard, native_plan, prd, standard_multi.
Uses SpecDetector for format detection and test case extraction.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedStep:
    index: int
    content: str
    expected: str = ""


@dataclass
class ParsedTestCase:
    title: str
    test_id: str = ""
    category: str = ""
    description: str = ""
    preconditions: str = ""
    steps: list[ParsedStep] = field(default_factory=list)
    expected_outcome: str = ""
    tags: list[str] = field(default_factory=list)
    section_path: list[str] = field(default_factory=list)


def parse_spec_file(
    spec_path: Path, metadata: dict | None = None, specs_dir: Path | None = None
) -> list[ParsedTestCase]:
    """
    Parse a spec file into structured test cases.

    Args:
        spec_path: Path to the markdown spec file
        metadata: Optional DB metadata dict with tags, description, etc.
        specs_dir: Base specs directory for deriving section_path

    Returns:
        List of ParsedTestCase objects
    """
    from utils.spec_detector import SpecDetector, SpecType

    if not spec_path.exists():
        raise FileNotFoundError(f"Spec not found: {spec_path}")

    spec_type = SpecDetector.detect_spec_type(spec_path)
    content = spec_path.read_text()

    # Derive section_path from folder structure relative to specs_dir
    section_path = _derive_section_path(spec_path, specs_dir)

    tags = []
    if metadata:
        tags = metadata.get("tags", [])

    # Multi-test specs: extract individual cases then parse each
    if spec_type in (SpecType.NATIVE_PLAN, SpecType.PRD, SpecType.STANDARD_MULTI):
        extracted = SpecDetector.extract_test_cases(spec_path)
        if extracted:
            cases = []
            for tc in extracted:
                case = _parse_markdown_to_testcase(tc["content"], tc.get("name", spec_path.stem))
                # Override with extracted metadata
                if tc.get("id"):
                    case.test_id = str(tc["id"])
                if tc.get("category"):
                    case.category = tc["category"]
                case.tags = tags
                # Section path: folder path + category as subsection
                case.section_path = list(section_path)
                if case.category and case.category != "Uncategorized":
                    case.section_path.append(case.category)
                cases.append(case)
            return cases

    # Standard single-test spec: parse directly
    case = _parse_markdown_to_testcase(content, spec_path.stem)
    case.tags = tags
    case.section_path = list(section_path)
    return [case]


def _derive_section_path(spec_path: Path, specs_dir: Path | None = None) -> list[str]:
    """Derive section hierarchy from the spec's folder path relative to specs_dir."""
    if specs_dir is None:
        return []

    try:
        rel = spec_path.relative_to(specs_dir)
    except ValueError:
        return []

    # Use parent folder parts as section path (exclude the filename)
    parts = list(rel.parent.parts)
    # Clean up folder names: replace hyphens/underscores with spaces, title case
    return [_clean_section_name(p) for p in parts if p != "."]


def _clean_section_name(name: str) -> str:
    """Convert folder name to a readable section name."""
    # Remove common prefixes like 'explorer-'
    cleaned = re.sub(r"^explorer-", "", name)
    # Replace hyphens and underscores with spaces
    cleaned = cleaned.replace("-", " ").replace("_", " ")
    # Title case
    return cleaned.strip().title()


def _parse_markdown_to_testcase(content: str, spec_name: str) -> ParsedTestCase:
    """
    Parse markdown content into a ParsedTestCase.

    Handles formats:
    - Title: '# Test: X', '### TC-NNN: X', '### Test N.N: X', '# Smoke Test: X'
    - Sections: '## Description', '## Preconditions', '## Steps', '## Expected Outcome'
    - Bold-label format: '**Steps**:', '**Expected Results**:'
    - Steps: lines matching numbered list items within the steps section
    """
    case = ParsedTestCase(title=spec_name)

    lines = content.split("\n")

    # Extract title
    for line in lines:
        # # Test: Title
        m = re.match(r"^#\s+(?:Smoke )?Test:\s*(.+)", line)
        if m:
            case.title = m.group(1).strip()
            break
        # ### TC-NNN: Title or #### TC-NNN: Title
        m = re.match(r"^#{3,4}\s+(?:Test\s+)?TC-(\d+):\s*(.+)", line)
        if m:
            case.test_id = f"TC-{m.group(1)}"
            case.title = m.group(2).strip()
            break
        # ### Test N.N: Title
        m = re.match(r"^#{3,4}\s+(?:Test\s+)?(\d+\.\d+)[:.]\s*(.+)", line)
        if m:
            case.test_id = m.group(1)
            case.title = m.group(2).strip()
            break

    # Parse sections using heading-based or bold-label detection
    current_section = None
    section_content: dict[str, list[str]] = {
        "description": [],
        "preconditions": [],
        "steps": [],
        "expected_outcome": [],
    }

    for line in lines:
        # Check for heading-based sections
        heading_match = re.match(r"^##\s+(.+)", line)
        if heading_match:
            heading = heading_match.group(1).strip().lower()
            if "description" in heading:
                current_section = "description"
                continue
            elif "precondition" in heading:
                current_section = "preconditions"
                continue
            elif "step" in heading:
                current_section = "steps"
                continue
            elif "expected" in heading or "outcome" in heading:
                current_section = "expected_outcome"
                continue
            elif "source" in heading:
                current_section = "source"
                continue
            else:
                current_section = None
                continue

        # Check for bold-label sections
        bold_match = re.match(r"^\*\*(.+?)\*\*\s*:", line)
        if bold_match:
            label = bold_match.group(1).strip().lower()
            if "step" in label:
                current_section = "steps"
                # Content may follow on the same line
                rest = line[bold_match.end() :].strip()
                if rest:
                    section_content["steps"].append(rest)
                continue
            elif "expected" in label:
                current_section = "expected_outcome"
                rest = line[bold_match.end() :].strip()
                if rest:
                    section_content["expected_outcome"].append(rest)
                continue
            elif "precondition" in label:
                current_section = "preconditions"
                rest = line[bold_match.end() :].strip()
                if rest:
                    section_content["preconditions"].append(rest)
                continue
            elif "description" in label:
                current_section = "description"
                rest = line[bold_match.end() :].strip()
                if rest:
                    section_content["description"].append(rest)
                continue

        if current_section and current_section in section_content:
            section_content[current_section].append(line)

    # Process description
    case.description = "\n".join(section_content["description"]).strip()

    # Process preconditions
    case.preconditions = "\n".join(section_content["preconditions"]).strip()

    # Process steps - extract numbered list items
    steps_text = "\n".join(section_content["steps"])
    case.steps = _extract_steps(steps_text)

    # Fallback: if no steps found via sections, scan entire content for numbered lines
    if not case.steps:
        case.steps = _extract_steps(content)

    # Process expected outcome
    expected_lines = section_content["expected_outcome"]
    # Clean up bullet points and join
    cleaned_expected = []
    for line in expected_lines:
        stripped = line.strip()
        if stripped and stripped != "-":
            # Remove leading bullet
            stripped = re.sub(r"^[-*]\s+", "", stripped)
            if stripped:
                cleaned_expected.append(stripped)
    case.expected_outcome = "\n".join(cleaned_expected)

    # Extract test ID from ## Source section if not already found
    if not case.test_id:
        id_match = re.search(r"^Test ID:\s*(.+?)$", content, re.MULTILINE)
        if id_match:
            case.test_id = id_match.group(1).strip()

    # Extract category from ## Source section if not already set
    if not case.category:
        cat_match = re.search(r"^Category:\s*(.+?)$", content, re.MULTILINE)
        if cat_match:
            case.category = cat_match.group(1).strip()

    return case


def _extract_steps(text: str) -> list[ParsedStep]:
    """Extract numbered steps from text."""
    steps = []
    # Match lines like "1. Step text" or "  1. Step text"
    for m in re.finditer(r"^\s*(\d+)\.\s+(.+)", text, re.MULTILINE):
        index = int(m.group(1))
        content = m.group(2).strip()
        steps.append(ParsedStep(index=index, content=content))
    return steps

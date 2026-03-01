"""
Export Utilities - Generates TestRail-compatible XML and CSV from parsed test cases.

Uses only stdlib modules (xml.etree.ElementTree, csv, io).
"""

import csv
import io
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

orchestrator_dir = Path(__file__).resolve().parent.parent
if str(orchestrator_dir) not in sys.path:
    sys.path.insert(0, str(orchestrator_dir))

from utils.spec_parser import ParsedTestCase


def generate_testrail_xml(test_cases: list[ParsedTestCase], project_name: str = "Exported Tests") -> str:
    """
    Generate TestRail XML import file from parsed test cases.

    Groups test cases by section_path into nested <section> elements.
    Uses <custom_steps_separated> with individual <step> elements.

    Args:
        test_cases: List of ParsedTestCase objects
        project_name: Name for the root section

    Returns:
        XML string ready for TestRail import
    """
    # TestRail expects <sections> as the root element
    root = ET.Element("sections")

    # Build section tree from test cases
    section_tree: dict = {}
    for tc in test_cases:
        path = tc.section_path if tc.section_path else ["Root"]
        _insert_into_tree(section_tree, path, tc)

    # Convert tree to XML
    _build_section_xml(root, section_tree)

    # Pretty-print with minidom
    rough_string = ET.tostring(root, encoding="unicode")
    dom = minidom.parseString(rough_string)
    pretty = dom.toprettyxml(indent="  ", encoding=None)

    # Remove the XML declaration line that minidom adds
    lines = pretty.split("\n")
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    result = "\n".join(lines).strip()

    # Wrap text content in CDATA where needed
    result = _add_cdata_wrapping(result)

    # Add XML declaration back at the top
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + result


def _insert_into_tree(tree: dict, path: list[str], tc: ParsedTestCase):
    """Insert a test case into the nested section tree at the given path."""
    node = tree
    for part in path:
        if part not in node:
            node[part] = {"_cases": [], "_children": {}}
        prev = node[part]
        node = prev["_children"]
    prev["_cases"].append(tc)


def _build_section_xml(parent: ET.Element, tree: dict):
    """Recursively build <section> XML elements from the section tree."""
    for name, data in tree.items():
        section = ET.SubElement(parent, "section")
        ET.SubElement(section, "name").text = name

        cases = data.get("_cases", [])
        children = data.get("_children", {})

        # TestRail requires cases wrapped in a <cases> container
        if cases:
            cases_container = ET.SubElement(section, "cases")
            for tc in cases:
                _build_case_xml(cases_container, tc)

        # Nested sections must be wrapped in a <sections> container
        if children:
            sections_container = ET.SubElement(section, "sections")
            _build_section_xml(sections_container, children)


def _build_case_xml(parent: ET.Element, tc: ParsedTestCase):
    """Build a <case> XML element for a single test case."""
    case = ET.SubElement(parent, "case")

    ET.SubElement(case, "title").text = tc.title
    ET.SubElement(case, "template").text = "Test Case (Steps)"
    ET.SubElement(case, "type").text = "Other"
    ET.SubElement(case, "priority").text = "Medium"

    if tc.test_id:
        ET.SubElement(case, "references").text = tc.test_id

    # Custom fields grouped under <custom>
    custom = ET.SubElement(case, "custom")

    # Preconditions
    preconds_text = tc.preconditions or tc.description
    if preconds_text:
        ET.SubElement(custom, "preconds").text = preconds_text

    # Separated steps
    if tc.steps:
        steps_sep = ET.SubElement(custom, "steps_separated")
        for step in tc.steps:
            step_elem = ET.SubElement(steps_sep, "step")
            ET.SubElement(step_elem, "index").text = str(step.index)
            ET.SubElement(step_elem, "content").text = step.content
            ET.SubElement(step_elem, "expected").text = step.expected

        # Add expected outcome as a final verification step
        if tc.expected_outcome:
            final_step = ET.SubElement(steps_sep, "step")
            ET.SubElement(final_step, "index").text = str(len(tc.steps) + 1)
            ET.SubElement(final_step, "content").text = "Verify expected outcomes"
            ET.SubElement(final_step, "expected").text = tc.expected_outcome


def _add_cdata_wrapping(xml_str: str) -> str:
    """
    Wrap text content of specific elements in CDATA sections.

    TestRail expects CDATA for multi-line content in preconds, content, expected.
    """
    import re

    def wrap_cdata(match):
        tag = match.group(1)
        content = match.group(2)
        # Only wrap if content contains special chars or newlines
        if content and ("&" in content or "<" in content or "\n" in content or "@" in content):
            return f"<{tag}><![CDATA[{content}]]></{tag}>"
        return match.group(0)

    for tag in ["preconds", "content", "expected"]:
        xml_str = re.sub(rf"<({tag})>(.*?)</{tag}>", wrap_cdata, xml_str, flags=re.DOTALL)

    return xml_str


def generate_testrail_csv(test_cases: list[ParsedTestCase], separated_steps: bool = True) -> str:
    """
    Generate TestRail CSV import file from parsed test cases.

    Args:
        test_cases: List of ParsedTestCase objects
        separated_steps: If True, use one row per step (TestRail separated steps format).
                        If False, concatenate all steps into a single row.

    Returns:
        CSV string ready for TestRail import
    """
    output = io.StringIO()

    if separated_steps:
        return _generate_csv_separated(test_cases, output)
    else:
        return _generate_csv_simple(test_cases, output)


def _generate_csv_separated(test_cases: list[ParsedTestCase], output: io.StringIO) -> str:
    """Generate CSV with separated steps (one row per step)."""
    headers = ["Section", "Title", "Type", "Priority", "Preconditions", "Step", "Expected Result", "References"]

    writer = csv.writer(output)
    writer.writerow(headers)

    for tc in test_cases:
        section = " > ".join(tc.section_path) if tc.section_path else "Root"
        refs = tc.test_id

        # Add tag references
        if tc.tags:
            tag_str = ", ".join(tc.tags)
            refs = f"{refs}, {tag_str}" if refs else tag_str

        preconds = tc.preconditions or tc.description

        if tc.steps:
            # First row: all metadata + first step
            first_step = tc.steps[0]
            writer.writerow(
                [
                    section,
                    tc.title,
                    "Functional",
                    "Medium",
                    preconds,
                    first_step.content,
                    first_step.expected,
                    refs,
                ]
            )

            # Subsequent rows: only step + expected
            for step in tc.steps[1:]:
                writer.writerow(
                    [
                        "",
                        "",
                        "",
                        "",
                        "",
                        step.content,
                        step.expected,
                        "",
                    ]
                )

            # Final verification step with expected outcome
            if tc.expected_outcome:
                writer.writerow(
                    [
                        "",
                        "",
                        "",
                        "",
                        "",
                        "Verify expected outcomes",
                        tc.expected_outcome,
                        "",
                    ]
                )
        else:
            # No steps - still export the test case
            writer.writerow(
                [
                    section,
                    tc.title,
                    "Functional",
                    "Medium",
                    preconds,
                    "",
                    tc.expected_outcome,
                    refs,
                ]
            )

    return output.getvalue()


def _generate_csv_simple(test_cases: list[ParsedTestCase], output: io.StringIO) -> str:
    """Generate CSV with all steps in a single row."""
    headers = ["Section", "Title", "Type", "Priority", "Preconditions", "Steps", "Expected Result", "References"]

    writer = csv.writer(output)
    writer.writerow(headers)

    for tc in test_cases:
        section = " > ".join(tc.section_path) if tc.section_path else "Root"
        refs = tc.test_id

        if tc.tags:
            tag_str = ", ".join(tc.tags)
            refs = f"{refs}, {tag_str}" if refs else tag_str

        preconds = tc.preconditions or tc.description

        # Join all steps into a single text block
        steps_text = "\n".join(f"{s.index}. {s.content}" for s in tc.steps)

        writer.writerow(
            [
                section,
                tc.title,
                "Functional",
                "Medium",
                preconds,
                steps_text,
                tc.expected_outcome,
                refs,
            ]
        )

    return output.getvalue()

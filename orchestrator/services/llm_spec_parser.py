"""
LLM Test Spec Parser - Parses markdown test specs into structured data.

Supports test suite definitions with system prompts, variables, defaults,
test cases with assertions, metrics, and judge configuration.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class JudgeConfig:
    """LLM-as-judge evaluation config for a test case."""

    rubric: str = ""
    criteria: list[str] = field(default_factory=list)
    threshold: float = 7.0
    scale_max: int = 10


@dataclass
class LlmTestCase:
    """Single test case within a suite."""

    id: str = ""
    name: str = ""
    input_prompt: str = ""
    expected_output: str = ""
    context: list[str] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    judge: JudgeConfig | None = None


@dataclass
class LlmTestSuite:
    """Parsed LLM test suite from markdown spec."""

    name: str = ""
    description: str = ""
    system_prompt: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    test_cases: list[LlmTestCase] = field(default_factory=list)


def parse_llm_spec(content: str) -> LlmTestSuite:
    """Parse a markdown LLM test spec into a structured LlmTestSuite.

    Args:
        content: Markdown content of the spec file

    Returns:
        LlmTestSuite with all parsed test cases and configuration
    """
    suite = LlmTestSuite()
    lines = content.split("\n")

    # Extract suite name from H1
    for line in lines:
        if line.startswith("# "):
            raw = line[2:].strip()
            suite.name = re.sub(r"^LLM Test Suite:\s*", "", raw, flags=re.IGNORECASE).strip()
            break

    # Split into sections by H2
    sections = _split_sections(lines, level=2)

    for heading, body in sections.items():
        heading_lower = heading.lower().strip()
        text = "\n".join(body).strip()

        if heading_lower == "description":
            suite.description = text
        elif heading_lower == "system prompt":
            suite.system_prompt = text
        elif heading_lower == "variables":
            suite.variables = _parse_key_value_list(body)
        elif heading_lower == "defaults":
            suite.defaults = _parse_defaults(body)
        elif heading_lower == "test cases":
            suite.test_cases = _parse_test_cases(body)

    # Apply variable substitution to system prompt and test cases
    if suite.variables:
        for var_name, var_value in suite.variables.items():
            placeholder = "{{" + var_name + "}}"
            suite.system_prompt = suite.system_prompt.replace(placeholder, var_value)
        _apply_variables(suite)

    logger.info(f"Parsed LLM spec '{suite.name}' with {len(suite.test_cases)} test cases")
    return suite


def _split_sections(lines: list[str], level: int = 2) -> dict[str, list[str]]:
    """Split lines into sections by heading level."""
    prefix = "#" * level + " "
    sections: dict[str, list[str]] = {}
    current_heading = None
    current_lines: list[str] = []

    for line in lines:
        if line.startswith(prefix) and not line.startswith(prefix + "#"):
            if current_heading is not None:
                sections[current_heading] = current_lines
            current_heading = line[len(prefix) :].strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = current_lines

    return sections


def _parse_key_value_list(lines: list[str]) -> dict[str, str]:
    """Parse lines like '- KEY: value' into a dict."""
    result = {}
    for line in lines:
        line = line.strip()
        m = re.match(r"^[-*]\s+(\w+)\s*:\s*(.+)$", line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


def _parse_defaults(lines: list[str]) -> dict[str, Any]:
    """Parse defaults section into typed values."""
    raw = _parse_key_value_list(lines)
    result: dict[str, Any] = {}
    for key, value in raw.items():
        # Try numeric conversion
        try:
            if "." in value:
                result[key] = float(value)
            else:
                result[key] = int(value)
        except ValueError:
            result[key] = value
    return result


def _parse_test_cases(lines: list[str]) -> list[LlmTestCase]:
    """Parse test cases from H3 subsections."""
    cases = []
    case_sections = _split_sections(lines, level=3)

    for heading, body in case_sections.items():
        case = LlmTestCase()

        # Parse ID and name from heading like "TC-001: Order Status Query"
        m = re.match(r"(TC-\d+)\s*:\s*(.+)", heading, re.IGNORECASE)
        if m:
            case.id = m.group(1)
            case.name = m.group(2).strip()
        else:
            case.id = heading.split(":")[0].strip() if ":" in heading else heading
            case.name = heading.split(":", 1)[1].strip() if ":" in heading else heading

        # Parse fields within the test case
        current_field = None
        field_lines: list[str] = []

        for line in body:
            # Match both **Field:** value and **Field**: value
            bold_match = re.match(r"\*\*([\w][\w\s]*?)(?::\s*)?\*\*\s*:?\s*(.*)", line.strip())
            if bold_match:
                # Save previous field
                if current_field:
                    _assign_case_field(case, current_field, field_lines)
                current_field = bold_match.group(1).strip().lower()
                first_value = bold_match.group(2).strip()
                field_lines = [first_value] if first_value else []
            elif current_field:
                field_lines.append(line)

        # Save last field
        if current_field:
            _assign_case_field(case, current_field, field_lines)

        if case.input_prompt:
            cases.append(case)

    return cases


def _assign_case_field(case: LlmTestCase, field_name: str, lines: list[str]):
    """Assign parsed field content to the test case."""
    text = "\n".join(lines).strip()

    if field_name in ("input", "input prompt"):
        case.input_prompt = text
    elif field_name in ("expected output", "expected", "expected response"):
        case.expected_output = text
    elif field_name == "context":
        case.context = [line.strip().lstrip("- ") for line in lines if line.strip().startswith("-")]
        if not case.context and text:
            case.context = [text]
    elif field_name == "assertions":
        case.assertions = _parse_assertions(lines)
    elif field_name == "metrics":
        case.metrics = _parse_metrics(lines)
    elif field_name == "judge":
        case.judge = _parse_judge(lines)


def _parse_assertions(lines: list[str]) -> list[dict[str, Any]]:
    """Parse assertion lines into structured dicts."""
    assertions = []
    for line in lines:
        line = line.strip().lstrip("- ")
        if not line:
            continue

        # Format: type: value
        m = re.match(r"([\w-]+)\s*:\s*(.+)", line)
        if m:
            atype = m.group(1).strip()
            avalue = m.group(2).strip()

            assertion = {"type": atype}
            # Numeric assertions
            if atype in ("latency-ms", "max-tokens", "cost-max", "min-length", "max-length"):
                try:
                    assertion["value"] = float(avalue)
                except ValueError:
                    assertion["value"] = avalue
            else:
                assertion["value"] = avalue

            assertions.append(assertion)

    return assertions


def _parse_metrics(lines: list[str]) -> dict[str, float]:
    """Parse metric lines like '- answer_relevancy: 0.8'."""
    metrics = {}
    for line in lines:
        line = line.strip().lstrip("- ")
        if not line:
            continue
        m = re.match(r"([\w_]+)\s*:\s*([\d.]+)", line)
        if m:
            try:
                metrics[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return metrics


def _parse_judge(lines: list[str]) -> JudgeConfig:
    """Parse judge configuration."""
    judge = JudgeConfig()
    for line in lines:
        line = line.strip().lstrip("- ")
        if not line:
            continue
        m = re.match(r"([\w]+)\s*:\s*(.+)", line)
        if m:
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            if key == "rubric":
                judge.rubric = value
            elif key == "criteria":
                judge.criteria = [c.strip() for c in value.split(",")]
            elif key == "threshold":
                try:
                    judge.threshold = float(value)
                except ValueError:
                    pass
            elif key == "scale_max" or key == "scale":
                try:
                    judge.scale_max = int(value)
                except ValueError:
                    pass
    return judge


def _apply_variables(suite: LlmTestSuite):
    """Substitute {{VAR}} placeholders in test cases."""
    for case in suite.test_cases:
        for var_name, var_value in suite.variables.items():
            placeholder = "{{" + var_name + "}}"
            case.input_prompt = case.input_prompt.replace(placeholder, var_value)
            case.expected_output = case.expected_output.replace(placeholder, var_value)
            for assertion in case.assertions:
                if isinstance(assertion.get("value"), str):
                    assertion["value"] = assertion["value"].replace(placeholder, var_value)
            if case.judge and case.judge.rubric:
                case.judge.rubric = case.judge.rubric.replace(placeholder, var_value)

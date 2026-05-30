"""Utilities for converting Playwright codegen output into Quorvex specs."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SENSITIVE_HINTS = (
    "password",
    "passcode",
    "secret",
    "token",
    "api key",
    "apikey",
    "access key",
    "şifrə",
    "sifre",
    "şifre",
    "parol",
)


@dataclass
class RecordedStep:
    action: str
    description: str
    expected: bool = False
    raw: str | None = None


@dataclass
class ParsedRecording:
    title: str
    target_url: str | None
    steps: list[RecordedStep] = field(default_factory=list)
    unsupported_lines: list[str] = field(default_factory=list)


def slugify(value: str, fallback: str = "recorded-flow") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80].strip("-") or fallback


def parse_playwright_codegen(code: str, title: str = "Recorded Flow", target_url: str | None = None) -> ParsedRecording:
    """Parse common Playwright codegen statements into human-readable test steps.

    This is intentionally conservative. Unsupported statements are preserved so
    the imported markdown never silently drops recorded behavior.
    """
    parsed = ParsedRecording(title=title.strip() or "Recorded Flow", target_url=target_url)

    for raw_line in code.splitlines():
        line = raw_line.strip()
        if not line.startswith("await "):
            continue

        line = line.removeprefix("await ").rstrip(";")
        step = _parse_action(line) or _parse_assertion(line)
        if step:
            parsed.steps.append(step)
        else:
            parsed.unsupported_lines.append(raw_line.strip())

    if parsed.target_url is None:
        for step in parsed.steps:
            match = re.match(r"Navigate to (.+)", step.description)
            if match:
                parsed.target_url = match.group(1)
                break

    return parsed


def build_markdown_spec(parsed: ParsedRecording, source_code_path: str | None = None) -> str:
    """Build a Quorvex markdown spec from parsed recording data."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = [
        f"# Test: {parsed.title}",
        "",
        "## Description",
        "Recorded from a Playwright codegen session and imported into Quorvex AI.",
        "",
        "## Source",
        f"- Recorded at: {now}",
    ]
    if parsed.target_url:
        lines.append(f"- Target URL: {parsed.target_url}")
    if source_code_path:
        lines.append(f"- Raw Playwright code: `{source_code_path}`")

    action_steps = [s for s in parsed.steps if not s.expected]
    expected_steps = [s for s in parsed.steps if s.expected]

    lines.extend(["", "## Steps"])
    if action_steps:
        for index, step in enumerate(action_steps, start=1):
            lines.append(f"{index}. {step.description}")
    else:
        lines.append("1. Review the raw Playwright recording and add user-facing steps.")

    lines.extend(["", "## Expected Outcome"])
    if expected_steps:
        for step in expected_steps:
            lines.append(f"- {step.description}")
    else:
        lines.append("- The recorded flow completes successfully without visible errors.")

    if parsed.unsupported_lines:
        lines.extend(["", "## Notes", "The following recorded Playwright statements need review:"])
        for raw in parsed.unsupported_lines:
            lines.append(f"- `{_escape_backticks(raw)}`")

    lines.append("")
    return "\n".join(lines)


def import_recording_to_spec(
    code_path: Path, title: str, target_url: str | None = None, source_code_path: str | None = None
) -> tuple[ParsedRecording, str]:
    code = code_path.read_text(encoding="utf-8")
    parsed = parse_playwright_codegen(code, title=title, target_url=target_url)
    return parsed, build_markdown_spec(parsed, source_code_path=source_code_path)


def _parse_action(line: str) -> RecordedStep | None:
    goto = re.match(r"page\.goto\((.+)\)$", line)
    if goto:
        url = _first_string(goto.group(1)) or goto.group(1)
        return RecordedStep(action="navigate", description=f"Navigate to {url}", raw=line)

    action = re.match(r"(.+)\.(click|dblclick|check|uncheck|hover)\((.*)\)$", line)
    if action:
        if _has_unsupported_chain(action.group(1)):
            return None
        locator = _describe_locator(action.group(1))
        verb = {
            "click": "Click",
            "dblclick": "Double-click",
            "check": "Check",
            "uncheck": "Uncheck",
            "hover": "Hover over",
        }[action.group(2)]
        return RecordedStep(action=action.group(2), description=f"{verb} {locator}", raw=line)

    fill = re.match(r"(.+)\.(fill|type)\((.*)\)$", line)
    if fill:
        if _has_unsupported_chain(fill.group(1)):
            return None
        locator = _describe_locator(fill.group(1))
        value = _redacted_value(_first_string(fill.group(3)) or "", locator)
        verb = "Enter" if fill.group(2) == "fill" else "Type"
        return RecordedStep(action=fill.group(2), description=f"{verb} {value} into {locator}", raw=line)

    select = re.match(r"(.+)\.selectOption\((.*)\)$", line)
    if select:
        if _has_unsupported_chain(select.group(1)):
            return None
        locator = _describe_locator(select.group(1))
        value = _first_string(select.group(2)) or "the recorded option"
        return RecordedStep(action="select", description=f"Select {value} in {locator}", raw=line)

    press = re.match(r"(.+)\.press\((.*)\)$", line)
    if press:
        if _has_unsupported_chain(press.group(1)):
            return None
        locator = _describe_locator(press.group(1))
        key = _first_string(press.group(2)) or "the recorded key"
        return RecordedStep(action="press", description=f"Press {key} in {locator}", raw=line)

    return None


def _has_unsupported_chain(expr: str) -> bool:
    return any(part in expr for part in (".filter(", ".nth(", ".first(", ".last(", ".and(", ".or("))


def _parse_assertion(line: str) -> RecordedStep | None:
    assertion = re.match(r"expect\((.+)\)\.(toBeVisible|toBeHidden|toContainText|toHaveText|toHaveValue|toBeChecked)\((.*)\)$", line)
    if not assertion:
        return None

    locator = _describe_locator(assertion.group(1))
    assertion_name = assertion.group(2)
    arg = _first_string(assertion.group(3))
    if assertion_name == "toBeVisible":
        description = f"{locator} is visible"
    elif assertion_name == "toBeHidden":
        description = f"{locator} is hidden"
    elif assertion_name == "toBeChecked":
        description = f"{locator} is checked"
    elif assertion_name == "toHaveValue":
        description = f"{locator} has value {_redacted_value(arg or 'the recorded value', locator)}"
    else:
        description = f"{locator} shows {arg or 'the recorded text'}"

    return RecordedStep(action="assert", description=description, expected=True, raw=line)


def _describe_locator(expr: str) -> str:
    expr = expr.strip()
    if ".locator(" in expr or expr.startswith("page.locator("):
        value = _first_string(expr.split(".locator(", 1)[1])
        return f"element `{value}`" if value else "the recorded element"

    match = re.search(r"page\.(getByRole|getByLabel|getByPlaceholder|getByText|getByTestId|getByTitle)\((.*)\)", expr)
    if not match:
        return "the recorded element"

    kind = match.group(1)
    args = match.group(2)
    first = _first_string(args)

    if kind == "getByRole":
        name = _name_option(args)
        return f"{first or 'element'} named `{name}`" if name else f"{first or 'element'}"
    if kind == "getByLabel":
        return f"field labeled `{first}`" if first else "the labeled field"
    if kind == "getByPlaceholder":
        return f"field with placeholder `{first}`" if first else "the placeholder field"
    if kind == "getByText":
        return f"text `{first}`" if first else "the recorded text"
    if kind == "getByTestId":
        return f"test id `{first}`" if first else "the recorded test id"
    if kind == "getByTitle":
        return f"element titled `{first}`" if first else "the titled element"
    return "the recorded element"


def _first_string(value: str) -> str | None:
    match = re.search(r"(['\"`])((?:\\.|(?!\1).)*)\1", value)
    if not match:
        return None
    return _decode_js_string(match.group(2))


def _name_option(value: str) -> str | None:
    match = re.search(r"name\s*:\s*(['\"`])((?:\\.|(?!\1).)*)\1", value)
    if not match:
        return None
    return _decode_js_string(match.group(2))


def _decode_js_string(value: str) -> str:
    if "\\" not in value:
        return value

    def replace_codepoint(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    decoded = re.sub(r"\\u\{([0-9a-fA-F]+)\}", replace_codepoint, value)
    decoded = re.sub(r"\\u([0-9a-fA-F]{4})", replace_codepoint, decoded)
    decoded = re.sub(r"\\x([0-9a-fA-F]{2})", replace_codepoint, decoded)
    escapes = {
        r"\n": "\n",
        r"\r": "\r",
        r"\t": "\t",
        r"\b": "\b",
        r"\f": "\f",
        r"\v": "\v",
        r"\\": "\\",
        r"\'": "'",
        r"\"": '"',
        r"\`": "`",
    }
    for escaped, replacement in escapes.items():
        decoded = decoded.replace(escaped, replacement)
    return decoded


def _redacted_value(value: str, locator: str) -> str:
    haystack = f"{locator} {value}".lower()
    if any(hint in haystack for hint in SENSITIVE_HINTS):
        password_hints = ("password", "passcode", "şifrə", "sifre", "şifre", "parol")
        name = "PASSWORD" if any(hint in haystack for hint in password_hints) else "SECRET_VALUE"
        return f"`{{{{{name}}}}}`"
    return f"`{_escape_backticks(value)}`"


def _escape_backticks(value: str) -> str:
    return value.replace("`", "\\`")

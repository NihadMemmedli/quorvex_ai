"""
Selector write-back: persists selectors from passing tests as memory patterns.

Closes the learning loop deterministically (no LLM): after a test passes (first
run or post-heal, stability-verified), selectors are extracted from the test
source and stored via MemoryManager.store_test_pattern(). Recall happens through
the existing path: unified._selector_patterns() -> context_builder ->
"selector patterns" prompt sections in the generator and healer.
"""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# getByRole('button', { name: 'Submit' }) / getByLabel('Email') / getByText("Hi") ...
_GETBY_CALL_RE = re.compile(r"getBy(Role|Label|TestId|Placeholder|Text|Title|AltText)\(")
_LOCATOR_CALL_RE = re.compile(r"\.locator\(")
_GOTO_RE = re.compile(r"page\.goto\(\s*['\"`]([^'\"`]+)['\"`]")
_TEST_TITLE_RE = re.compile(r"\btest(?:\.\w+)*\(\s*['\"`]([^'\"`]+)['\"`]")
_NAME_OPTION_RE = re.compile(r"\bname\s*:")

_ACTION_HINTS = (
    (".click(", "click"),
    (".fill(", "fill"),
    (".type(", "fill"),
    (".check(", "check"),
    (".uncheck(", "uncheck"),
    (".selectOption(", "select"),
    (".press(", "press"),
    (".hover(", "hover"),
    ("expect(", "assert"),
)

# Maps getBy* kind to the parsed-selector field used by store_test_pattern metadata
_ELEMENT_FIELD = {
    "Role": "element_role",
    "Label": "element_label",
    "TestId": "element_testid",
    "Placeholder": "element_placeholder",
    "Text": "element_text",
}


def _infer_action(line: str) -> str:
    for hint, action in _ACTION_HINTS:
        if hint in line:
            return action
    return "unknown"


def _parse_string_argument(text: str, start: int) -> tuple[str, int, int] | None:
    start = _skip_space(text, start)
    if start >= len(text) or text[start] not in {"'", '"', "`"}:
        return None

    quote = text[start]
    value_chars: list[str] = []
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            value_chars.append(text[index + 1])
            index += 2
            continue
        if char == quote:
            return "".join(value_chars), start, index + 1
        value_chars.append(char)
        index += 1
    return None


def _skip_space(text: str, start: int) -> int:
    while start < len(text) and text[start].isspace():
        start += 1
    return start


def _find_call_end(text: str, open_paren_index: int) -> int | None:
    depth = 0
    index = open_paren_index
    while index < len(text):
        char = text[index]
        if char in {"'", '"', "`"}:
            parsed = _parse_string_argument(text, index)
            if not parsed:
                return None
            index = parsed[2]
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _extract_name_option(call_text: str) -> str:
    match = _NAME_OPTION_RE.search(call_text)
    if not match:
        return ""
    parsed = _parse_string_argument(call_text, match.end())
    return parsed[0] if parsed else ""


def extract_selectors(test_content: str) -> list[dict]:
    """Extract selector usages from Playwright test source.

    Returns a list of dicts with: type, value, name, action, page_url,
    test_title, playwright_selector (verbatim locator expression).
    """
    selectors: list[dict] = []
    seen: set[tuple] = set()
    current_title = ""
    current_url = ""

    for line in test_content.splitlines():
        title_match = _TEST_TITLE_RE.search(line)
        if title_match:
            current_title = title_match.group(1)
            current_url = ""
        goto_match = _GOTO_RE.search(line)
        if goto_match:
            current_url = goto_match.group(1)

        action = _infer_action(line)

        for match in _GETBY_CALL_RE.finditer(line):
            kind = match.group(1)
            parsed_value = _parse_string_argument(line, match.end())
            call_end = _find_call_end(line, match.end() - 1)
            if not parsed_value or call_end is None:
                continue
            value = parsed_value[0]
            playwright_selector = line[match.start() : call_end]
            name = _extract_name_option(playwright_selector)
            key = (kind, value, name, action)
            if key in seen:
                continue
            seen.add(key)
            selectors.append(
                {
                    "type": f"getBy{kind}",
                    "value": value,
                    "name": name or "",
                    "action": action,
                    "page_url": current_url,
                    "test_title": current_title,
                    "playwright_selector": playwright_selector,
                }
            )

        for match in _LOCATOR_CALL_RE.finditer(line):
            parsed_css = _parse_string_argument(line, match.end())
            call_end = _find_call_end(line, match.end() - 1)
            if not parsed_css or call_end is None:
                continue
            css = parsed_css[0]
            key = ("locator", css, None, action)
            if key in seen:
                continue
            seen.add(key)
            selectors.append(
                {
                    "type": "locator",
                    "value": css,
                    "name": "",
                    "action": action,
                    "page_url": current_url,
                    "test_title": current_title,
                    "playwright_selector": line[match.start() : call_end].lstrip("."),
                }
            )

    return selectors


def selector_writeback_enabled() -> bool:
    return (
        os.environ.get("MEMORY_SELECTOR_WRITEBACK", "true").lower() == "true"
        and os.environ.get("MEMORY_ENABLED", "true").lower() == "true"
    )


def record_passing_test_selectors(
    test_path: str | Path,
    project_id: str | None = None,
    run_id: str | None = None,
) -> int:
    """Store selectors from a passing test as memory patterns. Returns count stored.

    Best-effort: never raises; gated by MEMORY_SELECTOR_WRITEBACK + MEMORY_ENABLED
    and requires a project id (arg or MEMORY_PROJECT_ID/PROJECT_ID env).
    """
    project_id = project_id or os.environ.get("MEMORY_PROJECT_ID") or os.environ.get("PROJECT_ID")
    if not selector_writeback_enabled() or not project_id:
        return 0

    try:
        path = Path(test_path)
        content = path.read_text()
        selectors = extract_selectors(content)
        if not selectors:
            return 0

        from orchestrator.memory.manager import get_memory_manager

        manager = get_memory_manager(project_id=project_id)
        stored = 0
        for step, sel in enumerate(selectors, start=1):
            selector_info = {
                "type": sel["type"],
                "value": sel["value"],
                "name": sel["name"],
                "strategy": sel["type"],
            }
            kind = sel["type"].removeprefix("getBy")
            field = _ELEMENT_FIELD.get(kind)
            if field:
                selector_info[field] = sel["value"]
                if field == "element_role" and sel["name"]:
                    selector_info["element_name"] = sel["name"]
            elif sel["type"] == "locator":
                selector_info["css_selector"] = sel["value"]

            manager.store_test_pattern(
                test_name=sel["test_title"] or path.stem,
                step_number=step,
                action=sel["action"],
                target=sel["name"] or sel["value"],
                selector=selector_info,
                success=True,
                metadata={
                    "page_url": sel["page_url"],
                    "playwright_selector": sel["playwright_selector"],
                    "spec_file": str(path),
                    **({"run_id": run_id} if run_id else {}),
                },
            )
            stored += 1

        logger.info("Selector write-back stored %d patterns from %s", stored, path.name)
        return stored
    except Exception as exc:
        logger.debug("Selector write-back skipped: %s", exc)
        return 0

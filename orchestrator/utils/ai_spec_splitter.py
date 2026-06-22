"""
AI-Powered Spec Splitter - Uses LLM to extract test cases from any markdown format.

Replaces brittle regex-based extraction with AI that naturally understands
any heading structure, ID format, and layout. Falls back gracefully when
API credentials are unavailable.
"""

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

# Add orchestrator to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from load_env import setup_claude_env
from orchestrator.services.ai_runtime_config import resolve_runtime_ai_selection
from orchestrator.utils.agent_runner import AgentRunner

setup_claude_env()


class AISpecSplitter:
    """
    Extract test cases from any markdown spec format using an LLM.

    Uses the configured Anthropic-compatible API endpoint with the configured
    model. This is a simple "markdown in, JSON out" task - no MCP tools needed.
    """

    CLAUDE_CODE_SUBSCRIPTION = "claude_code_subscription"
    DIRECT_API_KEY_ENV_KEYS = (
        "QUORVEX_LLM_API_KEY",
        "QUORVEX_LLM_API_KEYS",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKENS",
        "ZAI_API_KEY",
        "OPENAI_API_KEY",
    )
    MISSING_CREDENTIALS_MESSAGE = (
        "AI extraction requires either an API key credential or Claude Code subscription auth. "
        "Save an API key in Settings/.env, or configure/generate a Claude Code OAuth token in Settings."
    )

    @staticmethod
    def _env_value(env_vars: dict[str, str] | None, key: str) -> str:
        if env_vars is not None and key in env_vars:
            return env_vars.get(key, "")
        import os

        return os.environ.get(key, "")

    @classmethod
    def _has_explicit_direct_api_key(
        cls,
        env_vars: dict[str, str] | None,
        fallback_api_key: str,
    ) -> bool:
        if env_vars is not None and any(key in env_vars for key in cls.DIRECT_API_KEY_ENV_KEYS):
            for key in cls.DIRECT_API_KEY_ENV_KEYS:
                value = env_vars.get(key, "")
                if key in {"QUORVEX_LLM_API_KEYS", "ANTHROPIC_AUTH_TOKENS"}:
                    value = value.split(",", 1)[0].strip()
                if value:
                    return True
            return False
        return bool(fallback_api_key)

    @classmethod
    def _is_claude_code_subscription_mode(
        cls,
        runtime_env_vars: dict[str, str] | None,
        *,
        direct_api_key: str,
    ) -> bool:
        auth_mode = cls._env_value(runtime_env_vars, "QUORVEX_LLM_AUTH_MODE").strip().lower()
        provider = cls._env_value(runtime_env_vars, "QUORVEX_LLM_PROVIDER").strip().lower()
        oauth_token = cls._env_value(runtime_env_vars, "CLAUDE_CODE_OAUTH_TOKEN").strip()
        if auth_mode == cls.CLAUDE_CODE_SUBSCRIPTION or provider == cls.CLAUDE_CODE_SUBSCRIPTION:
            return True
        return bool(oauth_token and not direct_api_key)

    @staticmethod
    def _run_agent_sync(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result: dict[str, Any] = {}

        def _target() -> None:
            try:
                result["value"] = asyncio.run(coro)
            except BaseException as exc:  # pragma: no cover - re-raised below
                result["error"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join()
        if "error" in result:
            raise result["error"]
        return result.get("value")

    @classmethod
    def _call_claude_code_model(
        cls,
        prompt: str,
        runtime_env_vars: dict[str, str] | None,
    ) -> str:
        """Call Claude Code subscription runtime via AgentRunner and return response text."""
        runner = AgentRunner(
            allowed_tools=[],
            log_tools=False,
            model_tier="standard",
            env_vars=runtime_env_vars,
        )
        result = cls._run_agent_sync(runner.run(prompt))
        if not result or not getattr(result, "success", False):
            error = getattr(result, "error", None) or "Claude Code returned no successful result"
            raise RuntimeError(
                "Claude Code extraction failed. Check the Claude Code CLI, subscription login, "
                f"and OAuth token configuration in Settings. Details: {error}"
            )
        return getattr(result, "output", "") or ""

    @staticmethod
    def _call_text_model(api_key: str, base_url: str, model: str, prompt: str) -> str:
        """Call the configured text model and return the response text."""
        base_url = base_url.rstrip("/")
        if "openrouter.ai" in base_url.lower():
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            if not response or not response.choices:
                raise RuntimeError("AI returned empty choices - check API credentials and model availability")
            return response.choices[0].message.content or ""

        import httpx

        response = httpx.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4096,
                "temperature": 0.0,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60.0,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        content = data.get("content") or []
        text_parts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
        return "\n".join(part for part in text_parts if part)

    @classmethod
    def extract_test_cases(
        cls, content: str, spec_name: str = "", runtime_env_vars: dict[str, str] | None = None
    ) -> list[dict]:
        """
        Use AI to extract test cases from any markdown spec format.

        Args:
            content: Raw markdown content of the spec file
            spec_name: Name of the spec file (for context)

        Returns:
            List of test case dicts compatible with SpecDetector.extract_test_cases() format:
            - id: Test case ID (e.g., "TC-001")
            - name: Test case name
            - category: Test category
            - file_path: Suggested output file path (if present)
            - content: Reconstructed markdown content for individual spec
            - seed: Seed file reference (if present)

        Raises:
            RuntimeError: If API credentials are missing or AI call fails
        """
        selection = resolve_runtime_ai_selection("standard", env_vars=runtime_env_vars)
        api_key = selection.api_key
        base_url = selection.base_url
        model = selection.model
        direct_api_key = api_key if cls._has_explicit_direct_api_key(runtime_env_vars, api_key) else ""

        use_claude_code = cls._is_claude_code_subscription_mode(runtime_env_vars, direct_api_key=direct_api_key)
        if use_claude_code and not cls._env_value(runtime_env_vars, "CLAUDE_CODE_OAUTH_TOKEN").strip():
            raise RuntimeError(cls.MISSING_CREDENTIALS_MESSAGE)
        if not use_claude_code:
            if not api_key:
                raise RuntimeError(cls.MISSING_CREDENTIALS_MESSAGE)
            if not base_url:
                raise RuntimeError("QUORVEX_LLM_BASE_URL not set. Configure AI credentials in .env file or settings.")

        prompt = cls._build_extraction_prompt(content, spec_name)

        print(f"   Calling AI to extract test cases from {spec_name or 'spec'}...")
        sys.stdout.flush()

        try:
            if use_claude_code:
                result_text = cls._call_claude_code_model(prompt, runtime_env_vars)
            else:
                result_text = cls._call_text_model(api_key, base_url, model, prompt)
        except RuntimeError:
            raise  # Re-raise our own errors
        except Exception as e:
            raise RuntimeError(f"AI extraction failed: {e}")

        if not result_text or not result_text.strip():
            raise RuntimeError("AI returned empty response - check API credentials and connectivity")

        print(f"   AI response received ({len(result_text)} chars)")
        sys.stdout.flush()

        # Parse the AI response
        test_cases = cls._parse_ai_response(result_text)

        if not test_cases:
            preview = result_text[:500] if len(result_text) > 500 else result_text
            raise RuntimeError(
                f"AI responded but 0 test cases could be parsed. "
                f"Response preview ({len(result_text)} chars):\n{preview}"
            )

        # Convert AI output to legacy format (reconstruct content as markdown)
        return cls._convert_to_legacy_format(test_cases, content)

    @classmethod
    def extract_and_group(
        cls, content: str, spec_name: str = "", runtime_env_vars: dict[str, str] | None = None
    ) -> tuple:
        """
        Use AI to extract test cases AND suggest logical groupings.

        Returns:
            Tuple of (legacy_test_cases, groups) where:
            - legacy_test_cases: List[Dict] compatible with SpecDetector format
            - groups: List[Dict] with keys: name, test_ids, description

        Raises:
            RuntimeError: If API credentials are missing or AI call fails
        """
        selection = resolve_runtime_ai_selection("standard", env_vars=runtime_env_vars)
        api_key = selection.api_key
        base_url = selection.base_url
        model = selection.model
        direct_api_key = api_key if cls._has_explicit_direct_api_key(runtime_env_vars, api_key) else ""

        use_claude_code = cls._is_claude_code_subscription_mode(runtime_env_vars, direct_api_key=direct_api_key)
        if use_claude_code and not cls._env_value(runtime_env_vars, "CLAUDE_CODE_OAUTH_TOKEN").strip():
            raise RuntimeError(cls.MISSING_CREDENTIALS_MESSAGE)
        if not use_claude_code:
            if not api_key:
                raise RuntimeError(cls.MISSING_CREDENTIALS_MESSAGE)
            if not base_url:
                raise RuntimeError("QUORVEX_LLM_BASE_URL not set. Configure AI credentials in .env file or settings.")

        prompt = cls._build_grouping_prompt(content, spec_name)

        print(f"   Calling AI to extract and group test cases from {spec_name or 'spec'}...")
        sys.stdout.flush()

        try:
            if use_claude_code:
                result_text = cls._call_claude_code_model(prompt, runtime_env_vars)
            else:
                result_text = cls._call_text_model(api_key, base_url, model, prompt)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"AI extraction with grouping failed: {e}")

        if not result_text or not result_text.strip():
            raise RuntimeError("AI returned empty response - check API credentials and connectivity")

        print(f"   AI response received ({len(result_text)} chars)")
        sys.stdout.flush()

        # Parse the AI response for both test_cases and groups
        try:
            from utils.json_utils import extract_json_from_markdown
        except ImportError:
            from orchestrator.utils.json_utils import extract_json_from_markdown

        groups = []
        test_cases = []

        try:
            data = extract_json_from_markdown(result_text)
            if isinstance(data, dict):
                test_cases = data.get("test_cases", [])
                groups = data.get("groups", [])
            elif isinstance(data, list):
                test_cases = data
        except (ValueError, json.JSONDecodeError) as e:
            print(f"   Warning: Primary JSON extraction failed: {e}", flush=True)

        # Fallback: try code block extraction
        if not test_cases:
            test_cases = cls._parse_ai_response(result_text)

        if not test_cases:
            preview = result_text[:500] if len(result_text) > 500 else result_text
            raise RuntimeError(
                f"AI responded but 0 test cases could be parsed. "
                f"Response preview ({len(result_text)} chars):\n{preview}"
            )

        # Convert AI output to legacy format
        legacy_cases = cls._convert_to_legacy_format(test_cases, content)

        print(f"   Extracted {len(legacy_cases)} test cases in {len(groups)} groups")
        sys.stdout.flush()

        return legacy_cases, groups

    @classmethod
    def _build_grouping_prompt(cls, content: str, spec_name: str) -> str:
        """Build the prompt for AI test case extraction with grouping."""
        return f"""You are a test case extraction specialist. Analyze the following markdown test specification and extract ALL individual test cases, then suggest logical groupings.

## Input Spec
**File**: {spec_name}

```markdown
{content}
```

## Your Task

Extract every test case from this spec. Different specs use different formats (TC-001, Test 1.1, etc.) - handle any format.

For EACH test case, extract:
1. **id** - The test case ID exactly as written (e.g., "TC-001", "1.1", "Test 1")
2. **name** - The test case title/name
3. **category** - The category/suite it belongs to (e.g., "Happy Path Tests", "Edge Cases")
4. **description** - The test's OWN description (not the overview)
5. **preconditions** - Array of precondition strings (empty array if none)
6. **steps** - Array of step strings. IMPORTANT: preserve sub-items as part of the step text.
7. **expected_results** - Array of expected result strings
8. **selectors** - Array of selector hint strings (empty array if none mentioned)
9. **url** - Target URL if mentioned in the test or extractable from the overview (null if not found)
10. **file_path** - Suggested output file path if mentioned (null if not found)
11. **seed** - Seed file reference if mentioned (null if not found)

Also analyze relationships between test cases and suggest logical groupings:
- Group closely related tests that test the same feature/flow
- Each group should be 2-5 test cases
- Standalone tests with no close relatives should be in their own group
- Every test case must belong to exactly one group

## Output Format

Return a JSON object with both "test_cases" and "groups":

```json
{{
  "test_cases": [
    {{
      "id": "TC-001",
      "name": "View All Service Categories",
      "category": "Happy Path Tests",
      "description": "Verify that all service categories are displayed",
      "preconditions": ["User is on the homepage"],
      "steps": ["Navigate to /serviceCategories", "Verify page loads"],
      "expected_results": ["Page loads successfully"],
      "selectors": [],
      "url": "/serviceCategories",
      "file_path": null,
      "seed": null
    }}
  ],
  "groups": [
    {{
      "name": "Navigation Flow",
      "test_ids": ["TC-001", "TC-002", "TC-003"],
      "description": "Tests covering main navigation between pages"
    }}
  ]
}}
```

## Important Rules
- Extract ALL test cases, not just the first few
- Preserve the EXACT test ID format used in the document
- Include sub-items within steps (don't lose detail)
- If a step has numbered sub-items (like form fields), consolidate them into the step
- Every emitted test case must have a runnable URL whenever the parent spec has a target/base URL
- Prefer a test's explicit URL or first navigation step; if missing, use relative paths in that test's preconditions/steps/test data, resolved against the parent target origin
- Extract the URL from overview/environment section if tests don't have individual URLs or relative paths
- IMPORTANT: If the overview/environment section contains a base URL (e.g., https://example.com), resolve ALL relative URLs to absolute
- For authenticated tests that start from a dashboard or account precondition such as "/user/my_trips", use that deep link instead of the parent homepage fallback
- Every test case must appear in exactly one group
- Return ONLY the JSON, no other text"""

    @classmethod
    def _build_extraction_prompt(cls, content: str, spec_name: str) -> str:
        """Build the prompt for AI test case extraction."""
        return f"""You are a test case extraction specialist. Analyze the following markdown test specification and extract ALL individual test cases.

## Input Spec
**File**: {spec_name}

```markdown
{content}
```

## Your Task

Extract every test case from this spec. Different specs use different formats (TC-001, Test 1.1, etc.) - handle any format.

For EACH test case, extract:
1. **id** - The test case ID exactly as written (e.g., "TC-001", "1.1", "Test 1")
2. **name** - The test case title/name
3. **category** - The category/suite it belongs to (e.g., "Happy Path Tests", "Edge Cases")
4. **description** - The test's OWN description (not the overview)
5. **preconditions** - Array of precondition strings (empty array if none)
6. **steps** - Array of step strings. IMPORTANT: preserve sub-items as part of the step text. For example, if step 3 has sub-items like "- Resource Name: 'Test'", include them in the step string as "Fill in: Resource Name: 'Test', Type: Accommodation"
7. **expected_results** - Array of expected result strings
8. **selectors** - Array of selector hint strings (empty array if none mentioned)
9. **url** - Target URL if mentioned in the test or extractable from the overview (null if not found)
10. **file_path** - Suggested output file path if mentioned (null if not found)
11. **seed** - Seed file reference if mentioned (null if not found)

## Output Format

Return a JSON object with a "test_cases" array:

```json
{{
  "test_cases": [
    {{
      "id": "TC-001",
      "name": "View All Service Categories",
      "category": "Happy Path Tests",
      "description": "Verify that all service categories are displayed on the main categories page",
      "preconditions": ["User is on the homepage", "No authentication required"],
      "steps": [
        "Navigate to `/serviceCategories`",
        "Wait for page to fully load",
        "Verify page title contains 'service categories'",
        "Count and verify all category cards are visible"
      ],
      "expected_results": [
        "Page loads successfully with HTTP 200",
        "Multiple service categories are displayed",
        "Each category has a name, icon, and description"
      ],
      "selectors": [
        "page.getByRole('heading', {{ name: /categories/i }})",
        "page.locator('.category-card')"
      ],
      "url": "/serviceCategories",
      "file_path": null,
      "seed": null
    }}
  ]
}}
```

## Important Rules
- Extract ALL test cases, not just the first few
- Preserve the EXACT test ID format used in the document
- Include sub-items within steps (don't lose detail)
- If a step has numbered sub-items (like form fields), consolidate them into the step
- Every emitted test case must have a runnable URL whenever the parent spec has a target/base URL
- Prefer a test's explicit URL or first navigation step; if missing, use relative paths in that test's preconditions/steps/test data, resolved against the parent target origin
- Extract the URL from overview/environment section if tests don't have individual URLs or relative paths
- IMPORTANT: If the overview/environment section contains a base URL (e.g., https://example.com), resolve ALL relative URLs to absolute. For example, if base URL is "https://example.com" and a test navigates to "/serviceCategories", the url field should be "https://example.com/serviceCategories"
- For authenticated tests that start from a dashboard or account precondition such as "/user/my_trips", use that deep link instead of the parent homepage fallback
- Return ONLY the JSON, no other text"""

    @classmethod
    def _parse_ai_response(cls, response_text: str) -> list[dict]:
        """Parse the AI response into test case dicts."""
        from utils.json_utils import extract_json_from_markdown

        try:
            data = extract_json_from_markdown(response_text)
            if isinstance(data, dict) and "test_cases" in data:
                return data["test_cases"]
            elif isinstance(data, list):
                return data
        except (ValueError, json.JSONDecodeError) as e:
            print(f"   Warning: Primary JSON extraction failed: {e}", flush=True)

        # Fallback: try multiple code blocks
        import re

        json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        matches = re.findall(json_pattern, response_text)
        for json_str in matches:
            try:
                data = json.loads(json_str.strip())
                if isinstance(data, dict) and "test_cases" in data:
                    return data["test_cases"]
                elif isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue

        return []

    @classmethod
    def _convert_to_legacy_format(cls, ai_test_cases: list[dict], original_content: str) -> list[dict]:
        """
        Convert AI-extracted test cases to the legacy format expected by
        SpecDetector.extract_test_cases() and PRDSpecSplitter.

        The key addition: we reconstruct a rich 'content' markdown string
        from the structured AI data, so _create_individual_spec gets everything.
        """
        # Extract overview URL from original content as fallback
        overview_url = cls._extract_overview_url(original_content)

        # Extract base URL origin for resolving relative URLs
        base_url_origin = None
        if overview_url and overview_url.startswith("http"):
            from urllib.parse import urlparse

            parsed = urlparse(overview_url)
            base_url_origin = f"{parsed.scheme}://{parsed.netloc}"

        legacy_cases = []
        for tc in ai_test_cases:
            if not isinstance(tc, dict):
                continue

            tc_id = tc.get("id", f"TC-{len(legacy_cases) + 1:03d}")
            tc_name = tc.get("name", "Unnamed Test")
            tc_category = tc.get("category", "Uncategorized")
            tc_url = tc.get("url") or overview_url

            # Resolve relative URLs against base URL origin
            if tc_url and tc_url.startswith("/") and base_url_origin:
                tc_url = f"{base_url_origin}{tc_url}"

            # Reconstruct rich markdown content from structured data
            content_parts = [f"### {tc_id}: {tc_name}"]

            description = tc.get("description", "")
            if description:
                content_parts.append(f"\n**Description**: {description}")

            preconditions = tc.get("preconditions", [])
            if preconditions:
                content_parts.append("\n**Preconditions**:")
                for pre in preconditions:
                    content_parts.append(f"- {pre}")

            steps = tc.get("steps", [])
            if steps:
                content_parts.append("\n**Steps**:")
                for i, step in enumerate(steps, 1):
                    content_parts.append(f"{i}. {step}")

            expected_results = tc.get("expected_results", [])
            if expected_results:
                content_parts.append("\n**Expected Results**:")
                for result in expected_results:
                    content_parts.append(f"- {result}")

            selectors = tc.get("selectors", [])
            if selectors:
                content_parts.append("\n**Selectors to Use**:")
                for sel in selectors:
                    content_parts.append(f"- `{sel}`")

            if tc_url:
                content_parts.append(f"\n**URL**: {tc_url}")

            file_path = tc.get("file_path")
            if file_path:
                content_parts.append(f"\n**File**: `{file_path}`")

            seed = tc.get("seed")
            if seed:
                content_parts.append(f"\n**Seed**: `{seed}`")

            legacy_cases.append(
                {
                    "id": tc_id,
                    "name": tc_name,
                    "category": tc_category,
                    "file_path": file_path,
                    "content": "\n".join(content_parts),
                    "seed": seed,
                    # Extra fields for richer spec generation
                    "_ai_extracted": True,
                    "_description": description,
                    "_preconditions": preconditions,
                    "_steps": steps,
                    "_expected_results": expected_results,
                    "_selectors": selectors,
                    "_url": tc_url,
                }
            )

        return legacy_cases

    @classmethod
    def _extract_overview_url(cls, content: str) -> str | None:
        """Extract the target URL from spec overview/environment section."""
        import re

        # Try common patterns
        patterns = [
            r"\*\*(?:Target |Application )?URL\*?\*?:\s*(\S+)",
            r"\*\*(?:Base |Entry )?URL\*?\*?:\s*(\S+)",
            r"(?:Navigate to|Go to)\s+(`?https?://\S+`?)",
            r"(?:Navigate to|Go to)\s+(`?/\S+`?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                url = match.group(1).strip("`").strip()
                return url

        # Fallback: find any absolute URL in the document
        abs_url_match = re.search(r"(https?://[^\s\)\"\'`>]+)", content)
        if abs_url_match:
            return abs_url_match.group(1).rstrip(".,;:")

        return None


if __name__ == "__main__":
    """CLI usage: python ai_spec_splitter.py <spec_path>"""
    import argparse

    parser = argparse.ArgumentParser(description="AI-powered test case extraction")
    parser.add_argument("spec", help="Path to spec file")

    args = parser.parse_args()
    spec_path = Path(args.spec)

    if not spec_path.exists():
        print(f"File not found: {spec_path}")
        sys.exit(1)

    content = spec_path.read_text()
    try:
        test_cases = AISpecSplitter.extract_test_cases(content, spec_path.name)
        print(f"\nExtracted {len(test_cases)} test cases:")
        for tc in test_cases:
            print(f"  {tc['id']}. {tc['name']} ({tc['category']})")
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

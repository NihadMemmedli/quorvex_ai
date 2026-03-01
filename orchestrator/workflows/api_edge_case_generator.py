"""
API Edge Case Generator - Auto-generate edge case and security tests.

Given API endpoints (from exploration, OpenAPI, or manual spec), generates:
- Input validation tests: empty fields, boundary values, wrong types
- Auth edge cases: no token, expired token, wrong role
- Error handling: 404 for missing resources, 409 for conflicts
- Security: SQL injection payloads, XSS in text fields
"""

import asyncio
import os
import re
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

import logging

from orchestrator.utils.agent_runner import AgentRunner, get_default_timeout

logger = logging.getLogger(__name__)


class ApiEdgeCaseGenerator:
    """
    Generate edge case and security API tests from existing API specs.

    Takes an API spec and generates additional test files covering:
    - Input validation (empty, null, boundary, wrong type)
    - Authentication edge cases (missing, invalid, expired)
    - Error handling (404, 409, 422, 500)
    - Security (injection, XSS, CSRF)
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        if project_id and project_id != "default":
            self.tests_dir = BASE_DIR / "tests" / "generated" / project_id
        else:
            self.tests_dir = BASE_DIR / "tests" / "generated"
        self.tests_dir.mkdir(parents=True, exist_ok=True)

    async def generate(self, spec_path: str) -> list[Path]:
        """
        Generate edge case tests from an API spec.

        Args:
            spec_path: Path to the API spec file

        Returns:
            List of paths to generated test files
        """
        spec_file = Path(spec_path)
        if not spec_file.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_path}")

        spec_content = spec_file.read_text()
        spec_name = spec_file.stem

        logger.info(f"Generating edge case tests from: {spec_path}")

        generated_files = []

        # Generate validation edge cases
        validation_path = await self._generate_validation_tests(spec_name, spec_content)
        if validation_path:
            generated_files.append(validation_path)

        # Generate auth edge cases
        auth_path = await self._generate_auth_tests(spec_name, spec_content)
        if auth_path:
            generated_files.append(auth_path)

        # Generate security tests
        security_path = await self._generate_security_tests(spec_name, spec_content)
        if security_path:
            generated_files.append(security_path)

        return generated_files

    async def _generate_validation_tests(self, spec_name: str, spec_content: str) -> Path | None:
        """Generate input validation edge case tests."""
        output_path = self.tests_dir / f"{spec_name}.validation.api.spec.ts"

        prompt = f"""You are a Playwright API Test Generator specializing in INPUT VALIDATION edge cases.

Given the following API spec, generate tests that validate how the API handles bad input.

<spec>
{spec_content}
</spec>

## Generate Tests For:

1. **Empty/null fields**: Send requests with empty strings, null values, missing required fields
2. **Wrong types**: Send string where number expected, number where string expected
3. **Boundary values**: Max length strings, negative numbers, zero, MAX_INT
4. **Invalid formats**: Bad email format, invalid dates, malformed UUIDs
5. **Extra fields**: Send unexpected fields in request body

## Requirements:

- Use Playwright `request` fixture
- Each edge case is a separate test
- Assert appropriate error status codes (400, 422)
- Assert error response body has useful error messages
- Use `test.describe('Input Validation - {spec_name}', ...)`
- Write to: {output_path}

Return COMPLETE TypeScript code in a ```typescript block.
"""

        return await self._run_and_save(prompt, output_path)

    async def _generate_auth_tests(self, spec_name: str, spec_content: str) -> Path | None:
        """Generate authentication edge case tests."""
        output_path = self.tests_dir / f"{spec_name}.auth.api.spec.ts"

        prompt = f"""You are a Playwright API Test Generator specializing in AUTHENTICATION edge cases.

Given the following API spec, generate tests for authentication edge cases.

<spec>
{spec_content}
</spec>

## Generate Tests For:

1. **No auth**: Send requests without any authentication header
2. **Invalid token**: Send requests with malformed/random token
3. **Expired token**: Send request with clearly expired JWT (if applicable)
4. **Wrong auth type**: Use Basic auth when Bearer expected, etc.
5. **Empty token**: Send empty Authorization header

## Requirements:

- Use Playwright `request` fixture
- Assert 401 Unauthorized or 403 Forbidden responses
- Assert error response body has appropriate error messages
- Use `test.describe('Auth Edge Cases - {spec_name}', ...)`
- Write to: {output_path}

Return COMPLETE TypeScript code in a ```typescript block.
"""

        return await self._run_and_save(prompt, output_path)

    async def _generate_security_tests(self, spec_name: str, spec_content: str) -> Path | None:
        """Generate security edge case tests."""
        output_path = self.tests_dir / f"{spec_name}.security.api.spec.ts"

        prompt = f"""You are a Playwright API Test Generator specializing in SECURITY testing.

Given the following API spec, generate tests that check for common security vulnerabilities.

<spec>
{spec_content}
</spec>

## Generate Tests For:

1. **SQL Injection**: Send SQL payloads in text fields (e.g., "'; DROP TABLE users; --")
   - Assert the API does NOT return 500 (should handle gracefully)
2. **XSS**: Send script tags in text fields (e.g., "<script>alert('xss')</script>")
   - Assert response either sanitizes or rejects the input
3. **Path traversal**: Try accessing resources outside allowed scope (../../../etc/passwd)
4. **Large payloads**: Send oversized request bodies
   - Assert 413 or appropriate rejection
5. **Rate limiting**: Send many rapid requests (if applicable)
   - Assert 429 after threshold

## Requirements:

- Use Playwright `request` fixture
- These are DEFENSIVE tests - verify the API handles attacks gracefully
- Do NOT generate actual exploit code - only test that the API rejects malicious input
- Use `test.describe('Security Tests - {spec_name}', ...)`
- Write to: {output_path}

Return COMPLETE TypeScript code in a ```typescript block.
"""

        return await self._run_and_save(prompt, output_path)

    async def _run_and_save(self, prompt: str, output_path: Path) -> Path | None:
        """Run agent and save output."""
        timeout = int(os.environ.get("GENERATOR_TIMEOUT_SECONDS", get_default_timeout()))

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=["Glob", "Grep", "Read", "LS", "Write"],
            log_tools=True,
        )

        result = await runner.run(prompt)

        # Check if agent wrote the file
        if output_path.exists():
            content = output_path.read_text()
            if "test(" in content or "test.describe" in content:
                logger.info(f"   Generated: {output_path}")
                return output_path

        # Extract from response
        if result.output:
            for pattern in [r"```typescript\n(.*?)```", r"```ts\n(.*?)```"]:
                match = re.search(pattern, result.output, re.DOTALL)
                if match:
                    code = match.group(1).strip()
                    if "test(" in code or "test.describe" in code:
                        output_path.write_text(code)
                        logger.info(f"   Generated: {output_path}")
                        return output_path

        logger.warning(f"   Failed to generate: {output_path.name}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate API edge case tests")
    parser.add_argument("spec", help="Path to API spec file")
    parser.add_argument("--project-id", default="default")
    args = parser.parse_args()

    from orchestrator.logging_config import setup_logging

    setup_logging()

    async def main():
        gen = ApiEdgeCaseGenerator(project_id=args.project_id)
        results = await gen.generate(args.spec)
        logger.info(f"Generated {len(results)} edge case test files")

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise

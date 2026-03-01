"""
API Test From Exploration - Generate API tests from discovered endpoints.

The exploration system captures API endpoints in the `discovered_api_endpoints` table.
This workflow queries that data and generates Playwright API test suites.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
from orchestrator.utils.api_endpoint_filter import filter_api_endpoints, group_by_base_path

logger = logging.getLogger(__name__)


class ApiTestFromExploration:
    """
    Generate Playwright API tests from exploration-discovered endpoints.

    Flow:
    1. Query DiscoveredApiEndpoint for session_id
    2. Filter out third-party/static endpoints
    3. Group by base path
    4. For each group, AI generates comprehensive API test suite
    5. Write to tests/generated/api/{group-name}.api.spec.ts
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.tests_dir = BASE_DIR / "tests" / "generated" / "api"
        self.tests_dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        session_id: str,
    ) -> list[Path]:
        """
        Generate API test files from exploration session data.

        Args:
            session_id: Exploration session ID

        Returns:
            List of paths to generated test files
        """
        logger.info(f"Loading API endpoints from exploration session: {session_id}")

        # Load endpoints from database
        endpoints = self._load_endpoints(session_id)
        if not endpoints:
            logger.warning("No API endpoints found for this session")
            return []

        logger.info(f"   Found {len(endpoints)} raw endpoints")

        # Determine app domain from session
        app_domain = self._get_app_domain(session_id)

        # Filter noise
        filtered = filter_api_endpoints(endpoints, app_domain=app_domain)
        logger.info(f"   After filtering: {len(filtered)} endpoints")

        if not filtered:
            logger.warning("No API endpoints remained after filtering")
            return []

        # Group by base path
        groups = group_by_base_path(filtered)
        logger.info(f"   Grouped into {len(groups)} endpoint group(s)")
        for path, eps in groups.items():
            methods = set(ep.get("method", "?") for ep in eps)
            logger.info(f"     {path}: {len(eps)} endpoints ({', '.join(sorted(methods))})")

        # Generate tests for each group
        generated_files = []
        for base_path, group_endpoints in groups.items():
            try:
                test_path = await self._generate_group_tests(base_path, group_endpoints, app_domain)
                if test_path and test_path.exists():
                    generated_files.append(test_path)
            except Exception as e:
                logger.warning(f"   Failed to generate tests for {base_path}: {e}")

        return generated_files

    def _load_endpoints(self, session_id: str) -> list[dict[str, Any]]:
        """Load endpoints from the database."""
        try:
            from sqlmodel import Session, select

            from orchestrator.api.db import engine
            from orchestrator.api.models_db import DiscoveredApiEndpoint

            with Session(engine) as session:
                stmt = select(DiscoveredApiEndpoint).where(DiscoveredApiEndpoint.session_id == session_id)
                results = session.exec(stmt).all()

                return [
                    {
                        "method": ep.method,
                        "url": ep.url,
                        "request_headers": ep.request_headers,
                        "request_body_sample": ep.request_body_sample,
                        "response_status": ep.response_status,
                        "response_body_sample": ep.response_body_sample,
                        "triggered_by_action": ep.triggered_by_action,
                        "call_count": ep.call_count,
                    }
                    for ep in results
                ]

        except Exception as e:
            logger.error(f"   Database error: {e}")
            return []

    def _get_app_domain(self, session_id: str) -> str | None:
        """Get the application domain from the exploration session."""
        try:
            from sqlmodel import Session, select

            from orchestrator.api.db import engine
            from orchestrator.api.models_db import ExplorationSession

            with Session(engine) as session:
                stmt = select(ExplorationSession).where(ExplorationSession.id == session_id)
                result = session.exec(stmt).first()
                if result and result.entry_url:
                    parsed = urlparse(result.entry_url)
                    return parsed.hostname
        except Exception:
            pass
        return None

    async def _generate_group_tests(
        self, base_path: str, endpoints: list[dict[str, Any]], app_domain: str | None
    ) -> Path | None:
        """Generate a test file for a group of related endpoints."""
        # Create a clean filename from the base path
        group_name = base_path.strip("/").replace("/", "-") or "root"
        output_path = self.tests_dir / f"{group_name}.api.spec.ts"

        logger.info(f"Generating API tests for: {base_path}")

        # Build endpoint catalog for the prompt
        catalog_lines = []
        for ep in endpoints:
            line = f"  - {ep['method']} {ep['url']}"
            if ep.get("response_status"):
                line += f" (status: {ep['response_status']})"
            if ep.get("triggered_by_action"):
                line += f" [triggered by: {ep['triggered_by_action']}]"
            catalog_lines.append(line)

            # Add request/response samples if available
            if ep.get("request_body_sample"):
                body = ep["request_body_sample"][:500]
                catalog_lines.append(f"    Request body: {body}")
            if ep.get("response_body_sample"):
                body = ep["response_body_sample"][:500]
                catalog_lines.append(f"    Response body: {body}")

        catalog = "\n".join(catalog_lines)

        base_url = f"https://{app_domain}" if app_domain else "http://localhost:8001"

        prompt = f"""You are the Playwright API Test Generator.

Generate a comprehensive Playwright API test suite for the following discovered endpoints.

## Endpoint Group: {base_path}
## Base URL: {base_url}
## Output File: {output_path}

## Discovered Endpoints
{catalog}

## Instructions

1. Generate a complete Playwright TypeScript test file using `request` fixture
2. Test each discovered endpoint with the observed method and expected status
3. Use the request/response samples as guidance for test data
4. Group related operations (CRUD flows) using `test.describe.serial()`
5. Include both positive tests (observed behavior) and basic negative tests
6. Use `process.env.API_TOKEN!` for any auth headers
7. Add comments linking back to the UI action that triggered each endpoint

## Output

Return ONLY the complete TypeScript code inside a ```typescript code block.
Write the file to: {output_path}
"""

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

        # Extract code from response
        if result.output:
            import re

            for pattern in [r"```typescript\n(.*?)```", r"```ts\n(.*?)```"]:
                match = re.search(pattern, result.output, re.DOTALL)
                if match:
                    code = match.group(1).strip()
                    if "test(" in code or "test.describe" in code:
                        output_path.write_text(code)
                        logger.info(f"   Generated: {output_path}")
                        return output_path

        logger.warning(f"   Failed to generate tests for {base_path}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate API tests from exploration data")
    parser.add_argument("session_id", help="Exploration session ID")
    parser.add_argument("--project-id", default="default", help="Project ID")
    args = parser.parse_args()

    async def main():
        generator = ApiTestFromExploration(project_id=args.project_id)
        results = await generator.generate(session_id=args.session_id)
        logger.info(f"Generated {len(results)} test files")

    try:
        from orchestrator.logging_config import setup_logging

        setup_logging()
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise

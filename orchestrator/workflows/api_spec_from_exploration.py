"""
API Spec From Exploration - Generate markdown API specs from discovered endpoints.

The exploration system captures API endpoints in the `discovered_api_endpoints` table.
This workflow queries that data and generates human-readable markdown API spec files
that can be used as input to the existing API testing pipeline (NativeApiGenerator).
"""

import asyncio
import os
import re
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


class ApiSpecFromExploration:
    """
    Generate markdown API specs from exploration-discovered endpoints.

    Flow:
    1. Query DiscoveredApiEndpoint for session_id
    2. Filter out third-party/static endpoints
    3. Group by base path
    4. For each group, AI generates a markdown API spec
    5. Write to specs/generated/api/{group-name}.md
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.specs_dir = BASE_DIR / "specs" / "generated" / "api"
        self.specs_dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        session_id: str,
    ) -> list[Path]:
        """
        Generate markdown API spec files from exploration session data.

        Args:
            session_id: Exploration session ID

        Returns:
            List of paths to generated spec files

        Raises:
            RuntimeError: If no endpoints found or all filtered out
        """
        logger.info(f"Loading API endpoints from exploration session: {session_id}")

        # Load all session data in a single DB session
        session_data = self._load_session_data(session_id)
        endpoints = session_data["endpoints"]
        app_domain = session_data["app_domain"]
        base_url = session_data["base_url"]

        if not endpoints:
            raise RuntimeError(f"No API endpoints found for session {session_id}")

        logger.info(f"   Found {len(endpoints)} raw endpoints")

        # Filter noise
        filtered = filter_api_endpoints(endpoints, app_domain=app_domain)
        logger.info(f"   After filtering: {len(filtered)} endpoints")

        if not filtered:
            raise RuntimeError("No API endpoints remained after filtering")

        # Group by base path
        groups = group_by_base_path(filtered)
        logger.info(f"   Grouped into {len(groups)} endpoint group(s)")
        for path, eps in groups.items():
            methods = set(ep.get("method", "?") for ep in eps)
            logger.info(f"     {path}: {len(eps)} endpoints ({', '.join(sorted(methods))})")

        # Generate specs for each group
        generated_files = []
        for base_path, group_endpoints in groups.items():
            try:
                spec_path = await self._generate_group_spec(base_path, group_endpoints, app_domain, base_url)
                if spec_path and spec_path.exists():
                    if self._validate_spec_content(spec_path.read_text()):
                        generated_files.append(spec_path)
                    else:
                        logger.warning(f"   Generated spec for {base_path} failed validation, keeping anyway")
                        generated_files.append(spec_path)
            except Exception as e:
                logger.warning(f"   Failed to generate spec for {base_path}: {e}")

        return generated_files

    def _load_session_data(self, session_id: str) -> dict[str, Any]:
        """Load endpoints, app domain, and base URL in a single DB session."""
        from sqlmodel import Session as DBSession
        from sqlmodel import select

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import DiscoveredApiEndpoint, ExplorationSession

        app_domain: str | None = None
        base_url = "http://localhost:8001"
        endpoints: list[dict[str, Any]] = []

        with DBSession(engine) as session:
            # Load exploration session for domain/URL
            exploration = session.get(ExplorationSession, session_id)
            if exploration and exploration.entry_url:
                parsed = urlparse(exploration.entry_url)
                app_domain = parsed.hostname
                base_url = f"{parsed.scheme}://{parsed.netloc}"

            # Load endpoints
            stmt = select(DiscoveredApiEndpoint).where(DiscoveredApiEndpoint.session_id == session_id)
            results = session.exec(stmt).all()
            endpoints = [
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

        return {
            "endpoints": endpoints,
            "app_domain": app_domain,
            "base_url": base_url,
        }

    @staticmethod
    def _validate_spec_content(content: str) -> bool:
        """Check that generated markdown has basic API spec structure."""
        has_title = content.strip().startswith("# ")
        section_count = content.count("\n## ")
        has_http_method = any(method in content.upper() for method in ["GET", "POST", "PUT", "DELETE", "PATCH"])
        return has_title and section_count >= 2 and has_http_method

    async def _generate_group_spec(
        self,
        base_path: str,
        endpoints: list[dict[str, Any]],
        app_domain: str | None,
        base_url: str,
    ) -> Path | None:
        """Generate a markdown API spec file for a group of related endpoints."""
        # Create a clean filename from the base path
        group_name = base_path.strip("/").replace("/", "-") or "root"
        output_path = self.specs_dir / f"{group_name}.md"

        logger.info(f"Generating API spec for: {base_path}")

        # Build endpoint catalog for the prompt
        catalog_lines = []
        for ep in endpoints:
            line = f"### {ep['method']} {ep['url']}"
            catalog_lines.append(line)

            if ep.get("response_status"):
                catalog_lines.append(f"- **Observed Status**: {ep['response_status']}")

            if ep.get("triggered_by_action"):
                catalog_lines.append(f"- **Triggered By**: {ep['triggered_by_action']}")

            if ep.get("call_count", 0) > 1:
                catalog_lines.append(f"- **Call Count**: {ep['call_count']}x")

            # Add request headers if available
            headers = ep.get("request_headers")
            if headers and isinstance(headers, dict) and len(headers) > 0:
                catalog_lines.append("- **Request Headers**:")
                for k, v in headers.items():
                    catalog_lines.append(f"  - `{k}: {v}`")

            # Add request body if available
            if ep.get("request_body_sample"):
                body = ep["request_body_sample"][:1500]
                catalog_lines.append(f"- **Request Body Sample**:\n```json\n{body}\n```")

            # Add response body if available
            if ep.get("response_body_sample"):
                body = ep["response_body_sample"][:1500]
                catalog_lines.append(f"- **Response Body Sample**:\n```json\n{body}\n```")

            catalog_lines.append("")  # blank line between endpoints

        catalog = "\n".join(catalog_lines)

        prompt = f"""You are an API specification writer.

Generate a clean, well-structured markdown API specification from the following discovered endpoint data.

## Endpoint Group: {base_path}
## Base URL: {base_url}
## Output File: {output_path}

## Discovered Endpoints
{catalog}

## Instructions

Generate a markdown file with this structure:

1. **Title**: `# API Spec: {base_path}`
2. **Overview**: Brief description of what this API group does (infer from endpoints)
3. **Base URL**: `{base_url}`
4. **Authentication**: Document auth patterns found in headers (Bearer tokens, cookies, API keys)
5. **Endpoints**: For each endpoint:
   - Method and path
   - Description (inferred from URL pattern and request/response data)
   - Request headers (if available)
   - Request body schema (if available, inferred from samples)
   - Expected response (status code and body schema)
   - Example request/response
6. **Error Handling**: Common error patterns observed

## Important
- Use actual data from the discovered endpoints, don't fabricate data
- If request/response bodies are available, use them as examples
- Infer field types and required/optional from the samples
- Document any authentication patterns found in headers
- Keep the spec focused and practical - it will be used to generate API tests

## Output

Return ONLY the complete markdown content inside a ```markdown code block.
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
            if len(content) > 50:  # Basic sanity check
                logger.info(f"   Generated: {output_path}")
                return output_path

        # Extract markdown from response
        if result.output:
            for pattern in [r"```markdown\n(.*?)```", r"```md\n(.*?)```", r"```\n(# API.*?)```"]:
                match = re.search(pattern, result.output, re.DOTALL)
                if match:
                    content = match.group(1).strip()
                    if len(content) > 50:
                        output_path.write_text(content)
                        logger.info(f"   Generated: {output_path}")
                        return output_path

            # Last resort: if output starts with "# API" it might be the raw spec
            if result.output.strip().startswith("# API"):
                output_path.write_text(result.output.strip())
                logger.info(f"   Generated (raw): {output_path}")
                return output_path

        logger.warning(f"   Failed to generate spec for {base_path}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate API specs from exploration data")
    parser.add_argument("session_id", help="Exploration session ID")
    parser.add_argument("--project-id", default="default", help="Project ID")
    args = parser.parse_args()

    _result_files: list[Path] = []

    async def main():
        global _result_files
        generator = ApiSpecFromExploration(project_id=args.project_id)
        _result_files = await generator.generate(session_id=args.session_id)

    try:
        from orchestrator.logging_config import setup_logging

        setup_logging()
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise

    logger.info(f"Generated {len(_result_files)} spec files")

"""
OpenAPI/Swagger Processor - Import OpenAPI specs and generate API tests.

Accepts OpenAPI v3 JSON/YAML or Swagger v2, generates markdown API specs,
then feeds them through the API test pipeline.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

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

from orchestrator.workflows.native_api_generator import NativeApiGenerator

logger = logging.getLogger(__name__)


class OpenApiProcessor:
    """
    Process OpenAPI/Swagger specs into Playwright API tests.

    Flow:
    1. Load and parse OpenAPI spec (JSON or YAML)
    2. Extract endpoints, parameters, request bodies, response schemas, auth
    3. Group endpoints by tag or path prefix
    4. For each group, generate a markdown API spec
    5. Feed each spec through the API test pipeline
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        if project_id and project_id != "default":
            self.specs_dir = BASE_DIR / "specs" / project_id / "generated" / "api"
        else:
            self.specs_dir = BASE_DIR / "specs" / "generated" / "api"
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self.api_generator = NativeApiGenerator(project_id=project_id)

    async def process(self, openapi_path_or_url: str, feature_filter: str | None = None) -> list[Path]:
        """
        Process an OpenAPI spec and generate API tests.

        Args:
            openapi_path_or_url: Path to JSON/YAML file or URL
            feature_filter: Optional tag/group filter

        Returns:
            List of paths to generated test files
        """
        logger.info(f"Loading OpenAPI spec: {openapi_path_or_url}")

        # Load the spec
        spec = self._load_spec(openapi_path_or_url)
        if not spec:
            raise ValueError(f"Failed to load OpenAPI spec from: {openapi_path_or_url}")

        # Determine spec version
        version = self._detect_version(spec)
        logger.info(f"   Version: {version}")

        # Extract base URL
        base_url = self._extract_base_url(spec, version)
        logger.info(f"   Base URL: {base_url}")

        # Extract security schemes
        auth_info = self._extract_auth(spec, version)
        if auth_info:
            logger.info(f"   Auth: {auth_info['type']}")

        # Extract and group endpoints
        endpoints = self._extract_endpoints(spec, version)
        logger.info(f"   Endpoints: {len(endpoints)}")

        # Group by tag
        groups = self._group_endpoints(endpoints)
        logger.info(f"   Groups: {len(groups)}")

        # Apply feature filter
        if feature_filter:
            filter_lower = feature_filter.lower()
            groups = {k: v for k, v in groups.items() if filter_lower in k.lower()}
            logger.info(f"   Filtered to {len(groups)} group(s) matching '{feature_filter}'")

        # Generate specs and tests for each group
        generated_tests = []
        for group_name, group_endpoints in groups.items():
            slug = self._slugify(group_name)
            test_path = None
            try:
                # Generate markdown spec
                spec_path = self._generate_spec(group_name, group_endpoints, base_url, auth_info)
                logger.info(f"Generated spec: {spec_path}")

                # Generate test from spec
                test_path = await self.api_generator.generate_test(
                    str(spec_path), target_url=base_url, output_name=f"openapi-{slug}"
                )

            except Exception as e:
                if "cancel scope" in str(e).lower():
                    # SDK cleanup error - file may have been written despite the error
                    logger.info(f"   Cancel scope error for '{group_name}', checking for generated file...")
                else:
                    logger.warning(f"   Failed to process group '{group_name}': {e}")

            # Check for generated file regardless of cancel scope errors
            if test_path and test_path.exists():
                generated_tests.append(test_path)
            else:
                # Fallback: check expected path directly (file may exist despite SDK error)
                expected_path = self.api_generator.tests_dir / f"openapi-{slug}.api.spec.ts"
                if expected_path.exists():
                    logger.info(f"   Found generated file despite error: {expected_path}")
                    generated_tests.append(expected_path)

        return generated_tests

    def _load_spec(self, path_or_url: str) -> dict | None:
        """Load OpenAPI spec from file or URL."""
        content = None

        if path_or_url.startswith(("http://", "https://")):
            # Fetch from URL
            try:
                import urllib.request

                with urllib.request.urlopen(path_or_url) as response:
                    content = response.read().decode("utf-8")
            except Exception as e:
                logger.error(f"   Failed to fetch URL: {e}")
                return None
        else:
            # Read from file
            path = Path(path_or_url)
            if not path.exists():
                logger.error(f"   File not found: {path_or_url}")
                return None
            content = path.read_text()

        if not content:
            return None

        # Try JSON first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try YAML
        try:
            import yaml

            parsed = yaml.safe_load(content)
            if isinstance(parsed, dict):
                return parsed
            logger.error("   YAML parsed but result is not a valid OpenAPI object")
            return None
        except ImportError:
            logger.warning("   PyYAML not installed - only JSON specs supported")
            return None
        except Exception:
            pass

        return None

    def _detect_version(self, spec: dict) -> str:
        """Detect OpenAPI/Swagger version."""
        if "openapi" in spec:
            return f"OpenAPI {spec['openapi']}"
        elif "swagger" in spec:
            return f"Swagger {spec['swagger']}"
        return "Unknown"

    def _extract_base_url(self, spec: dict, version: str) -> str:
        """Extract base URL from spec."""
        # OpenAPI 3.x
        if "servers" in spec and spec["servers"]:
            return spec["servers"][0].get("url", "https://api.example.com")

        # Swagger 2.x
        if "host" in spec:
            scheme = "https"
            if "schemes" in spec and spec["schemes"]:
                scheme = spec["schemes"][0]
            base_path = spec.get("basePath", "")
            return f"{scheme}://{spec['host']}{base_path}"

        return "https://api.example.com"

    def _extract_auth(self, spec: dict, version: str) -> dict | None:
        """Extract authentication info from spec."""
        # OpenAPI 3.x
        components = spec.get("components", {})
        security_schemes = components.get("securitySchemes", {})

        # Swagger 2.x
        if not security_schemes:
            security_schemes = spec.get("securityDefinitions", {})

        for _name, scheme in security_schemes.items():
            scheme_type = scheme.get("type", "")

            if scheme_type == "http" and scheme.get("scheme") == "bearer":
                return {"type": "Bearer", "env_var": "API_TOKEN"}
            elif scheme_type == "apiKey":
                location = scheme.get("in", "header")
                key_name = scheme.get("name", "X-API-Key")
                return {"type": "API Key", "location": location, "name": key_name, "env_var": "API_KEY"}
            elif scheme_type == "http" and scheme.get("scheme") == "basic":
                return {"type": "Basic", "env_var_user": "API_USER", "env_var_pass": "API_PASS"}
            elif scheme_type == "oauth2":
                return {"type": "Bearer", "env_var": "API_TOKEN"}

        return None

    def _extract_endpoints(self, spec: dict, version: str) -> list[dict]:
        """Extract all endpoints from the spec."""
        endpoints = []
        paths = spec.get("paths", {})

        for path, path_item in paths.items():
            for method in ["get", "post", "put", "patch", "delete"]:
                if method not in path_item:
                    continue

                operation = path_item[method]
                endpoint = {
                    "path": path,
                    "method": method.upper(),
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", ""),
                    "tags": operation.get("tags", []),
                    "parameters": operation.get("parameters", []),
                    "request_body": None,
                    "responses": operation.get("responses", {}),
                    "operation_id": operation.get("operationId", ""),
                }

                # Extract request body (OpenAPI 3.x)
                if "requestBody" in operation:
                    rb = operation["requestBody"]
                    content = rb.get("content", {})
                    if "application/json" in content:
                        schema = content["application/json"].get("schema", {})
                        endpoint["request_body"] = self._schema_to_example(schema, spec)

                # Extract request body (Swagger 2.x - body parameter)
                for param in endpoint["parameters"]:
                    if param.get("in") == "body" and "schema" in param:
                        endpoint["request_body"] = self._schema_to_example(param["schema"], spec)

                endpoints.append(endpoint)

        return endpoints

    def _schema_to_example(self, schema: dict, spec: dict, depth: int = 0) -> Any:
        """Convert a JSON schema to an example value."""
        if depth > 5:
            return {}

        # Resolve $ref
        if "$ref" in schema:
            ref_path = schema["$ref"]
            resolved = self._resolve_ref(ref_path, spec)
            if resolved:
                return self._schema_to_example(resolved, spec, depth + 1)
            return {}

        schema_type = schema.get("type", "object")

        if "example" in schema:
            return schema["example"]

        if schema_type == "string":
            format_type = schema.get("format", "")
            if format_type == "email":
                return "test@example.com"
            elif format_type == "date-time":
                return "2024-01-01T00:00:00Z"
            elif format_type == "uuid":
                return "550e8400-e29b-41d4-a716-446655440000"
            return "string"
        elif schema_type == "integer":
            return 1
        elif schema_type == "number":
            return 1.0
        elif schema_type == "boolean":
            return True
        elif schema_type == "array":
            items = schema.get("items", {})
            return [self._schema_to_example(items, spec, depth + 1)]
        elif schema_type == "object":
            obj = {}
            properties = schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                obj[prop_name] = self._schema_to_example(prop_schema, spec, depth + 1)
            return obj

        return {}

    def _resolve_ref(self, ref_path: str, spec: dict) -> dict | None:
        """Resolve a $ref path in the spec."""
        if not ref_path.startswith("#/"):
            return None

        parts = ref_path[2:].split("/")
        current = spec
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current if isinstance(current, dict) else None

    def _group_endpoints(self, endpoints: list[dict]) -> dict[str, list[dict]]:
        """Group endpoints by tag or path prefix."""
        groups: dict[str, list[dict]] = {}

        for ep in endpoints:
            # Use first tag if available, otherwise path prefix
            if ep["tags"]:
                group_name = ep["tags"][0]
            else:
                # Extract first two path segments
                parts = [p for p in ep["path"].split("/") if p and not p.startswith("{")]
                group_name = parts[0] if parts else "general"

            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(ep)

        return groups

    def _generate_spec(self, group_name: str, endpoints: list[dict], base_url: str, auth_info: dict | None) -> Path:
        """Generate a markdown API spec for a group of endpoints."""
        slug = self._slugify(group_name)
        spec_path = self.specs_dir / f"{slug}.md"

        lines = [
            f"# Test: {group_name.title()} API",
            "",
            "## Type: API",
            f"## Base URL: {base_url}",
        ]

        # Auth section
        if auth_info:
            if auth_info["type"] == "Bearer":
                lines.append(f"## Auth: Bearer {{{{{auth_info['env_var']}}}}}")
            elif auth_info["type"] == "API Key":
                lines.append(f"## Auth: {auth_info['name']}: {{{{{auth_info['env_var']}}}}}")

        lines.extend(["", "## Steps"])

        step_num = 1
        for ep in endpoints:
            method = ep["method"]
            path = ep["path"]
            summary = ep.get("summary", "")

            # Add comment with summary
            if summary:
                lines.append(f"# {summary}")

            # Build step
            step = f"{step_num}. {method} {path}"
            if ep.get("request_body"):
                body_json = json.dumps(ep["request_body"])
                step += f" with body {body_json}"
            lines.append(step)
            step_num += 1

            # Add assertion for primary success response
            for status_code, _response_info in ep.get("responses", {}).items():
                if status_code.startswith("2"):
                    lines.append(f"{step_num}. Verify response status is {status_code}")
                    step_num += 1
                    break

        lines.extend(["", "## Expected Outcome"])
        lines.append(f"- All {group_name} API endpoints respond with expected status codes")
        lines.append("- Response bodies match the documented schemas")

        spec_path.write_text("\n".join(lines))
        return spec_path

    def _slugify(self, text: str) -> str:
        """Convert text to a URL-friendly slug."""
        slug = text.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate API tests from OpenAPI spec")
    parser.add_argument("spec", help="Path or URL to OpenAPI/Swagger spec")
    parser.add_argument("--feature", help="Filter by tag/feature name")
    parser.add_argument("--project-id", default="default", help="Project ID")
    args = parser.parse_args()

    async def main():
        processor = OpenApiProcessor(project_id=args.project_id)
        results = await processor.process(args.spec, feature_filter=args.feature)
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

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

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

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


@dataclass
class OpenApiImportResult:
    """Structured result for a chat/API OpenAPI import job."""

    plan_path: Path | None = None
    evidence_paths: list[Path] = field(default_factory=list)
    spec_paths: list[Path] = field(default_factory=list)
    test_paths: list[Path] = field(default_factory=list)
    matched_operations: int = 0
    executed_operations: int = 0
    blocked_operations: list[dict[str, Any]] = field(default_factory=list)
    failed_operations: list[dict[str, Any]] = field(default_factory=list)
    skipped_operations: int = 0
    skipped_endpoints: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    selected_methods: list[str] = field(default_factory=list)
    chunk_count: int = 0
    recommended_mode: str = "plan_and_tests"
    recommended_next_action: str = "Review generated API specs and tests."
    resolved_source_url: str | None = None
    base_url: str | None = None
    needs_input: bool = False
    missing_fields: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved_source_url": self.resolved_source_url,
            "base_url": self.base_url,
            "needs_input": self.needs_input,
            "missing_fields": self.missing_fields,
            "plan_path": str(self.plan_path) if self.plan_path else None,
            "evidence_paths": [str(path) for path in self.evidence_paths],
            "spec_paths": [str(path) for path in self.spec_paths],
            "test_paths": [str(path) for path in self.test_paths],
            "matched_operations": self.matched_operations,
            "executed_operations": self.executed_operations,
            "blocked_operations": self.blocked_operations,
            "failed_operations": self.failed_operations,
            "skipped_operations": self.skipped_operations,
            "chunk_count": self.chunk_count,
            "recommended_mode": self.recommended_mode,
            "recommended_next_action": self.recommended_next_action,
            "skipped_endpoints": self.skipped_endpoints,
            "warnings": self.warnings,
            "selected_methods": self.selected_methods,
            "diagnostics": self.diagnostics,
            # Backward-compatible alias used by existing UI job consumers.
            "files": [str(path) for path in self.test_paths],
        }


class OperationPlannerSubagent:
    """Creates deterministic review-plan items for a chunk of operations."""

    def plan_chunk(self, operations: list[dict], chunk_index: int) -> list[dict[str, Any]]:
        plan_items = []
        for index, operation in enumerate(operations, start=1):
            success_codes = [
                str(code)
                for code in operation.get("responses", {})
                if str(code).startswith("2")
            ]
            plan_items.append(
                {
                    "id": f"chunk-{chunk_index:03d}-op-{index:03d}",
                    "method": operation["method"],
                    "path": operation["path"],
                    "operation_id": operation.get("operation_id") or "",
                    "summary": operation.get("summary") or operation.get("description") or "",
                    "tags": operation.get("tags", []),
                    "success_status": success_codes[0] if success_codes else "2xx",
                    "has_request_body": operation.get("request_body") is not None,
                }
            )
        return plan_items


class ApiSpecWriterSubagent:
    """Turns observed evidence into markdown API specs."""

    def __init__(self, processor: "OpenApiProcessor"):
        self.processor = processor

    def write_spec(
        self,
        group_name: str,
        operations: list[dict],
        base_url: str,
        auth_info: dict | None,
        evidence: list[dict[str, Any]],
        analysis: dict[str, Any],
        evidence_path: Path | None,
    ) -> Path:
        return self.processor._generate_evidence_spec(
            group_name,
            operations,
            base_url,
            auth_info,
            evidence,
            analysis,
            evidence_path,
        )


class RequestExecutionSubagent:
    """Executes documented operations and records redacted request/response evidence."""

    def __init__(self, processor: "OpenApiProcessor"):
        self.processor = processor

    async def execute_chunk(
        self,
        operations: list[dict[str, Any]],
        *,
        base_url: str,
        auth_info: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return await self.processor._execute_operations(operations, base_url=base_url, auth_info=auth_info)


class ResponseAnalysisSubagent:
    """Summarizes observed HTTP behavior into assertions and response shapes."""

    def __init__(self, processor: "OpenApiProcessor"):
        self.processor = processor

    def analyze_chunk(self, operations: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        return self.processor._analyze_evidence(operations, evidence)


class ApiCodegenSubagent:
    """Wraps the existing Playwright API generator."""

    def __init__(self, processor: "OpenApiProcessor"):
        self.processor = processor

    async def generate(self, spec_path: Path, output_name: str, base_url: str) -> Path | None:
        return await self.processor.api_generator.generate_test(
            str(spec_path), target_url=base_url, output_name=output_name
        )


class ReviewMergeAgent:
    """Deduplicates generated artifacts and builds the final import result."""

    @staticmethod
    def merge(
        *,
        plan_path: Path | None,
        spec_paths: list[Path],
        test_paths: list[Path],
        matched_operations: int,
        executed_operations: int,
        evidence_paths: list[Path],
        blocked_operations: list[dict[str, Any]],
        failed_operations: list[dict[str, Any]],
        skipped_endpoints: list[dict[str, Any]],
        warnings: list[str],
        selected_methods: list[str],
        chunk_count: int,
        recommended_mode: str,
        recommended_next_action: str,
        resolved_source_url: str | None,
        base_url: str | None = None,
        needs_input: bool = False,
        missing_fields: list[str] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> OpenApiImportResult:
        return OpenApiImportResult(
            plan_path=plan_path,
            evidence_paths=list(dict.fromkeys(evidence_paths)),
            spec_paths=list(dict.fromkeys(spec_paths)),
            test_paths=list(dict.fromkeys(test_paths)),
            matched_operations=matched_operations,
            executed_operations=executed_operations,
            blocked_operations=blocked_operations,
            failed_operations=failed_operations,
            skipped_operations=len(skipped_endpoints),
            skipped_endpoints=skipped_endpoints,
            warnings=list(dict.fromkeys(warnings)),
            selected_methods=selected_methods,
            chunk_count=chunk_count,
            recommended_mode=recommended_mode,
            recommended_next_action=recommended_next_action,
            resolved_source_url=resolved_source_url,
            base_url=base_url,
            needs_input=needs_input,
            missing_fields=missing_fields or [],
            diagnostics=diagnostics or {},
        )


class ImportCoordinatorAgent:
    """Fetches, validates, indexes, filters, chunks, and coordinates generation."""

    def __init__(self, processor: "OpenApiProcessor"):
        self.processor = processor

    async def run(
        self,
        openapi_path_or_url: str,
        *,
        feature_filter: str | None = None,
        method_filter: list[str] | None = None,
        mode: str = "plan_and_tests",
        base_url: str | None = None,
        server_url: str | None = None,
    ) -> OpenApiImportResult:
        logger.info(f"Loading OpenAPI spec: {openapi_path_or_url}")

        spec = self.processor._load_spec(openapi_path_or_url)
        if not spec:
            raise ValueError(f"Failed to load OpenAPI spec from: {openapi_path_or_url}")

        version = self.processor._detect_version(spec)
        logger.info(f"   Version: {version}")
        base_url, base_url_diagnostic = self.processor._resolve_base_url(spec, version, base_url or server_url)
        logger.info(f"   Base URL: {base_url or 'missing'}")
        auth_info = self.processor._extract_auth(spec, version)
        if auth_info:
            logger.info(f"   Auth: {auth_info['type']}")

        operations = self.processor._index_operations(spec, version)
        logger.info(f"   Operations indexed: {len(operations)}")
        matched, skipped = self.processor._filter_operations(
            operations,
            feature_filter=feature_filter,
            method_filter=method_filter,
        )
        selected_methods = self.processor._normalize_method_filter(method_filter)
        warnings: list[str] = []
        if not base_url:
            warning = "OpenAPI import needs a real API Server URL before specs or tests can be generated."
            warnings.append(warning)
            return ReviewMergeAgent.merge(
                plan_path=None,
                spec_paths=[],
                test_paths=[],
                matched_operations=len(matched),
                executed_operations=0,
                evidence_paths=[],
                blocked_operations=[],
                failed_operations=[],
                skipped_endpoints=skipped,
                warnings=warnings,
                selected_methods=selected_methods,
                chunk_count=0,
                recommended_mode=mode,
                recommended_next_action="Enter the API Server URL and re-run the import.",
                resolved_source_url=self.processor.resolved_source_url,
                base_url=None,
                needs_input=True,
                missing_fields=["base_url"],
                diagnostics={"base_url": base_url_diagnostic},
            )
        if feature_filter or selected_methods:
            logger.info(
                "   Filtered to %s operation(s), skipped %s",
                len(matched),
                len(skipped),
            )

        if not matched:
            warnings.append("No OpenAPI operations matched the requested filters.")
            return ReviewMergeAgent.merge(
                plan_path=None,
                spec_paths=[],
                test_paths=[],
                matched_operations=0,
                executed_operations=0,
                evidence_paths=[],
                blocked_operations=[],
                failed_operations=[],
                skipped_endpoints=skipped,
                warnings=warnings,
                selected_methods=selected_methods,
                chunk_count=0,
                recommended_mode=mode,
                recommended_next_action="Adjust the filters and re-run the import.",
                resolved_source_url=self.processor.resolved_source_url,
                base_url=base_url,
            )

        chunks = self.processor._chunk_operations(matched)
        recommended_mode = mode
        if len(chunks) > 1:
            warnings.append(f"Matched operations were split into {len(chunks)} chunks.")

        planner = OperationPlannerSubagent()
        spec_writer = ApiSpecWriterSubagent(self.processor)
        codegen = ApiCodegenSubagent(self.processor)

        all_plan_items: list[dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            all_plan_items.extend(planner.plan_chunk(chunk, chunk_index))

        plan_path = None
        if mode in {"plan_only", "plan_and_tests"}:
            plan_path = self.processor._generate_plan(
                all_plan_items,
                base_url=base_url,
                feature_filter=feature_filter,
                method_filter=selected_methods,
            )

        spec_paths: list[Path] = []
        evidence_paths: list[Path] = []
        chunk_specs: list[tuple[int, str, Path]] = []
        executed_operations = 0
        blocked_operations: list[dict[str, Any]] = []
        failed_operations: list[dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            group_name = self.processor._chunk_group_name(
                chunk,
                chunk_index,
                len(chunks),
                selected_methods,
                evidence=mode == "evidence_specs",
            )
            slug = self.processor._slugify(group_name)
            try:
                if mode == "evidence_specs":
                    executor = RequestExecutionSubagent(self.processor)
                    analyzer = ResponseAnalysisSubagent(self.processor)
                    evidence = await executor.execute_chunk(chunk, base_url=base_url, auth_info=auth_info)
                    evidence_path = self.processor._write_evidence(slug, evidence)
                    analysis = analyzer.analyze_chunk(chunk, evidence)
                    spec_path = spec_writer.write_spec(
                        group_name,
                        chunk,
                        base_url,
                        auth_info,
                        evidence,
                        analysis,
                        evidence_path,
                    )
                    evidence_paths.append(evidence_path)
                    executed_operations += sum(1 for item in evidence if item.get("status") == "executed")
                    blocked_operations.extend(item for item in evidence if item.get("status") == "blocked")
                    failed_operations.extend(item for item in evidence if item.get("status") == "failed")
                else:
                    spec_path = self.processor._generate_spec(group_name, chunk, base_url, auth_info)
                spec_paths.append(spec_path)
                chunk_specs.append((chunk_index, slug, spec_path))
                logger.info(f"Generated spec: {spec_path}")
            except Exception as e:
                warning = f"Failed to write chunk spec '{group_name}': {e}"
                logger.warning(f"   {warning}")
                warnings.append(warning)

        test_paths: list[Path] = []
        if mode in {"tests_only", "plan_and_tests"} and chunk_specs:
            concurrency = self.processor._codegen_concurrency()
            semaphore = asyncio.Semaphore(concurrency)

            async def generate_chunk(chunk_index: int, slug: str, spec_path: Path) -> tuple[int, Path | None, str | None]:
                test_path = None
                try:
                    async with semaphore:
                        test_path = await codegen.generate(spec_path, f"openapi-{slug}", base_url)
                except Exception as e:
                    if "cancel scope" in str(e).lower():
                        logger.info(f"   Cancel scope error for '{slug}', checking for generated file...")
                    else:
                        return chunk_index, None, f"Failed to process chunk '{slug}': {e}"

                if test_path and test_path.exists():
                    return chunk_index, test_path, None

                expected_path = self.processor.api_generator.tests_dir / f"openapi-{slug}.api.spec.ts"
                if expected_path.exists():
                    logger.info(f"   Found generated file despite error: {expected_path}")
                    return chunk_index, expected_path, None
                return chunk_index, None, None

            generated = await asyncio.gather(
                *(generate_chunk(chunk_index, slug, spec_path) for chunk_index, slug, spec_path in chunk_specs)
            )
            for _chunk_index, test_path, warning in sorted(generated, key=lambda item: item[0]):
                if warning:
                    logger.warning(f"   {warning}")
                    warnings.append(warning)
                if test_path:
                    test_paths.append(test_path)

        if blocked_operations:
            warnings.append(f"{len(blocked_operations)} operation(s) were blocked because required input could not be generated.")
        if failed_operations:
            warnings.append(f"{len(failed_operations)} operation(s) failed during evidence collection; failures were captured as evidence.")
        recommended_next_action = (
            "Generate Playwright API tests from the generated API specs."
            if mode in {"plan_only", "evidence_specs"} and spec_paths
            else "Review generated tests and run the API test suite."
            if test_paths
            else "Review generated API specs and re-run with adjusted filters or credentials."
        )

        return ReviewMergeAgent.merge(
            plan_path=plan_path,
            evidence_paths=evidence_paths,
            spec_paths=spec_paths,
            test_paths=test_paths,
            matched_operations=len(matched),
            executed_operations=executed_operations,
            blocked_operations=blocked_operations,
            failed_operations=failed_operations,
            skipped_endpoints=skipped,
            warnings=warnings,
            selected_methods=selected_methods,
            chunk_count=len(chunks),
            recommended_mode=recommended_mode,
            recommended_next_action=recommended_next_action,
            resolved_source_url=self.processor.resolved_source_url,
            base_url=base_url,
            diagnostics={
                "blocked_operations": blocked_operations,
                "failed_operations": failed_operations,
                "warnings": warnings,
            },
        )


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
        self.resolved_source_url: str | None = None
        if project_id and project_id != "default":
            self.specs_dir = BASE_DIR / "specs" / project_id / "generated" / "api"
        else:
            self.specs_dir = BASE_DIR / "specs" / "generated" / "api"
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self.api_generator = NativeApiGenerator(project_id=project_id)

    async def process(
        self,
        openapi_path_or_url: str,
        feature_filter: str | None = None,
        method_filter: list[str] | None = None,
        mode: str = "plan_and_tests",
    ) -> list[Path]:
        """
        Process an OpenAPI spec and generate API tests.

        Args:
            openapi_path_or_url: Path to JSON/YAML file or URL
            feature_filter: Optional tag/group filter
            method_filter: Optional HTTP method filter, for example ["POST"]
            mode: Import mode. Kept for compatibility; this method returns test paths.

        Returns:
            List of paths to generated test files
        """
        result = await self.process_import(
            openapi_path_or_url,
            feature_filter=feature_filter,
            method_filter=method_filter,
            mode=mode,
        )
        return result.test_paths

    async def process_import(
        self,
        openapi_path_or_url: str,
        *,
        feature_filter: str | None = None,
        method_filter: list[str] | None = None,
        mode: str = "plan_and_tests",
        base_url: str | None = None,
        server_url: str | None = None,
    ) -> OpenApiImportResult:
        """Process an OpenAPI spec and return plan/spec/test artifact metadata."""
        if mode not in {"evidence_specs", "plan_only", "tests_only", "plan_and_tests"}:
            raise ValueError(f"Unsupported OpenAPI import mode: {mode}")
        coordinator = ImportCoordinatorAgent(self)
        return await coordinator.run(
            openapi_path_or_url,
            feature_filter=feature_filter,
            method_filter=method_filter,
            mode=mode,
            base_url=base_url,
            server_url=server_url,
        )

    def _load_spec(self, path_or_url: str) -> dict | None:
        """Load OpenAPI spec from file or URL."""
        content = None
        self.resolved_source_url = path_or_url

        if path_or_url.startswith(("http://", "https://")):
            # Fetch from URL
            try:
                import urllib.request

                with urllib.request.urlopen(path_or_url, timeout=30) as response:
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

        swagger_ui_spec_url = self._extract_swagger_ui_spec_url(content, path_or_url)
        if swagger_ui_spec_url and swagger_ui_spec_url != path_or_url:
            logger.info(f"   Resolved Swagger UI URL to spec document: {swagger_ui_spec_url}")
            return self._load_spec(swagger_ui_spec_url)

        return None

    def _extract_swagger_ui_spec_url(self, content: str, source_url: str) -> str | None:
        """Resolve common Swagger UI/ReDoc pages to their JSON spec URL."""
        if not source_url.startswith(("http://", "https://")):
            return None
        if not re.search(r"SwaggerUIBundle|swagger-ui|redoc|openapi", content, re.IGNORECASE):
            return None

        for pattern in [
            r"url:\s*['\"]([^'\"]+)['\"]",
            r"spec-url=['\"]([^'\"]+)['\"]",
            r"data-url=['\"]([^'\"]+)['\"]",
        ]:
            match = re.search(pattern, content)
            if match:
                return urljoin(source_url, match.group(1))

        parsed = urlparse(source_url)
        if parsed.path.rstrip("/").endswith("/docs") or parsed.path.rstrip("/").endswith("/redoc"):
            return urljoin(source_url, "/openapi.json")
        return None

    def _detect_version(self, spec: dict) -> str:
        """Detect OpenAPI/Swagger version."""
        if "openapi" in spec:
            return f"OpenAPI {spec['openapi']}"
        elif "swagger" in spec:
            return f"Swagger {spec['swagger']}"
        return "Unknown"

    def _resolve_base_url(self, spec: dict, version: str, override: str | None = None) -> tuple[str | None, str]:
        if override and override.strip():
            candidate = override.strip()
            if self._is_usable_base_url(candidate):
                return candidate.rstrip("/"), "override"
            return None, f"Provided API Server URL is not usable: {candidate}"

        candidate = self._extract_base_url(spec, version)
        if candidate and self._is_usable_base_url(candidate):
            return candidate.rstrip("/"), "openapi_servers"
        if candidate:
            return None, f"OpenAPI server URL is missing or placeholder: {candidate}"
        return None, "OpenAPI document does not define a usable servers URL."

    def _extract_base_url(self, spec: dict, version: str) -> str | None:
        """Extract base URL from spec."""
        # OpenAPI 3.x
        if "servers" in spec and spec["servers"]:
            url = spec["servers"][0].get("url")
            if not isinstance(url, str) or not url.strip():
                return None
            url = url.strip()
            if isinstance(url, str) and url.startswith("/") and self.resolved_source_url:
                if str(self.resolved_source_url).startswith(("http://", "https://")):
                    return urljoin(self.resolved_source_url, url)
                return None
            return url

        # Swagger 2.x
        if "host" in spec:
            scheme = "https"
            if "schemes" in spec and spec["schemes"]:
                scheme = spec["schemes"][0]
            base_path = spec.get("basePath", "")
            return f"{scheme}://{spec['host']}{base_path}"

        return None

    def _is_usable_base_url(self, base_url: str | None) -> bool:
        if not base_url:
            return False
        if "{" in base_url or "}" in base_url:
            return False
        parsed = urlparse(base_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and not self._is_placeholder_base_url(base_url)

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

    def _index_operations(self, spec: dict, version: str) -> list[dict]:
        """Extract all operations from the spec in deterministic path/method order."""
        operations = []
        paths = spec.get("paths", {})

        for path in sorted(paths):
            path_item = paths.get(path, {})
            if not isinstance(path_item, dict):
                continue
            path_parameters = path_item.get("parameters", [])
            for method in HTTP_METHODS:
                if method not in path_item:
                    continue

                operation = path_item[method]
                if not isinstance(operation, dict):
                    continue
                parameters = []
                for raw_param in [*path_parameters, *operation.get("parameters", [])]:
                    if isinstance(raw_param, dict) and "$ref" in raw_param:
                        parameters.append(self._resolve_ref(raw_param["$ref"], spec) or raw_param)
                    else:
                        parameters.append(raw_param)
                endpoint = {
                    "path": path,
                    "method": method.upper(),
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", ""),
                    "tags": operation.get("tags", []),
                    "parameters": parameters,
                    "request_body": None,
                    "request_body_schema": None,
                    "request_body_required": False,
                    "responses": operation.get("responses", {}),
                    "operation_id": operation.get("operationId", ""),
                    "schemas": self._schemas_for_operation(spec, path_item, operation),
                }

                # Extract request body (OpenAPI 3.x)
                if "requestBody" in operation:
                    rb = operation["requestBody"]
                    if "$ref" in rb:
                        rb = self._resolve_ref(rb["$ref"], spec) or {}
                    endpoint["request_body_required"] = bool(rb.get("required"))
                    content = rb.get("content", {})
                    if "application/json" in content:
                        media_type = content["application/json"]
                        schema = media_type.get("schema", {})
                        endpoint["request_body_schema"] = self._dereference_schema(schema, spec)
                        endpoint["request_body"] = self._media_type_example(media_type, schema, spec)
                        if endpoint["request_body_required"] and not self._has_example_source(media_type, schema):
                            endpoint["request_body"] = None

                # Extract request body (Swagger 2.x - body parameter)
                for param in endpoint["parameters"]:
                    if param.get("in") == "body" and "schema" in param:
                        endpoint["request_body_required"] = bool(param.get("required"))
                        endpoint["request_body_schema"] = self._dereference_schema(param["schema"], spec)
                        endpoint["request_body"] = self._schema_to_example(param["schema"], spec)
                        if endpoint["request_body_required"] and not self._has_example_source(param, param["schema"]):
                            endpoint["request_body"] = None

                operations.append(endpoint)

        return operations

    def _media_type_example(self, media_type: dict[str, Any], schema: dict[str, Any], spec: dict[str, Any]) -> Any:
        if "example" in media_type:
            return media_type["example"]
        examples = media_type.get("examples")
        if isinstance(examples, dict) and examples:
            first = next(iter(examples.values()))
            if isinstance(first, dict) and "value" in first:
                return first["value"]
        return self._schema_to_example(schema, spec)

    def _has_example_source(self, container: dict[str, Any], schema: dict[str, Any]) -> bool:
        if any(key in container for key in ("example", "examples")):
            return True
        if not isinstance(schema, dict):
            return False
        if any(key in schema for key in ("example", "default", "enum", "type", "properties", "items", "allOf", "oneOf", "anyOf", "$ref")):
            return True
        return False

    def _extract_endpoints(self, spec: dict, version: str) -> list[dict]:
        """Backward-compatible alias for older tests/callers."""
        return self._index_operations(spec, version)

    def _normalize_method_filter(self, method_filter: list[str] | None) -> list[str]:
        if not method_filter:
            return []
        normalized = []
        for method in method_filter:
            if not isinstance(method, str):
                continue
            method_upper = method.strip().upper()
            if method_upper and method_upper.lower() in HTTP_METHODS and method_upper not in normalized:
                normalized.append(method_upper)
        return normalized

    def _filter_operations(
        self,
        operations: list[dict],
        *,
        feature_filter: str | None = None,
        method_filter: list[str] | None = None,
    ) -> tuple[list[dict], list[dict[str, Any]]]:
        """Filter by HTTP method before feature/tag/path filters."""
        selected_methods = set(self._normalize_method_filter(method_filter))
        feature_lower = feature_filter.lower() if feature_filter else None
        matched = []
        skipped = []

        for operation in operations:
            reason = None
            if selected_methods and operation["method"] not in selected_methods:
                reason = "method_filter"
            elif feature_lower and not self._operation_matches_feature(operation, feature_lower):
                reason = "feature_filter"

            if reason:
                skipped.append(
                    {
                        "method": operation["method"],
                        "path": operation["path"],
                        "operation_id": operation.get("operation_id", ""),
                        "reason": reason,
                    }
                )
            else:
                matched.append(operation)

        return matched, skipped

    def _operation_matches_feature(self, operation: dict, feature_lower: str) -> bool:
        haystack = [
            operation.get("path", ""),
            operation.get("summary", ""),
            operation.get("description", ""),
            operation.get("operation_id", ""),
            *operation.get("tags", []),
        ]
        return any(feature_lower in str(item).lower() for item in haystack)

    def _chunk_operations(self, operations: list[dict], chunk_size: int = 20) -> list[list[dict]]:
        """Split operations so large specs are never processed as one prompt/input."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        return [operations[i : i + chunk_size] for i in range(0, len(operations), chunk_size)]

    def _codegen_concurrency(self) -> int:
        try:
            return max(1, int(os.environ.get("OPENAPI_IMPORT_CODEGEN_CONCURRENCY", "2")))
        except ValueError:
            return 2

    def _chunk_group_name(
        self,
        operations: list[dict],
        chunk_index: int,
        total_chunks: int,
        selected_methods: list[str] | None = None,
        evidence: bool = False,
    ) -> str:
        groups = self._group_endpoints(operations)
        if len(groups) == 1:
            base = next(iter(groups.keys()))
            path_group = self._path_group_name(operations)
            if path_group and path_group not in base:
                base = f"{base}-{path_group}"
        elif selected_methods:
            base = "-".join(method.lower() for method in selected_methods) + "-operations"
        else:
            base = "openapi-operations"
        suffix = "evidence" if evidence else "operations"
        if total_chunks > 1:
            return f"{base}-{suffix}-{chunk_index:03d}"
        return f"{base}-{suffix}"

    def _path_group_name(self, operations: list[dict[str, Any]]) -> str:
        segments: list[str] = []
        for operation in operations:
            for part in operation.get("path", "").split("/"):
                if part and not part.startswith("{"):
                    segments.append(part)
                    break
        unique = list(dict.fromkeys(segments))
        if len(unique) == 1:
            return unique[0]
        return ""

    def _schema_to_example(self, schema: dict, spec: dict, depth: int = 0) -> Any:
        """Convert a JSON schema to an example value."""
        if not isinstance(schema, dict) or depth > 5:
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
        if "default" in schema:
            return schema["default"]
        if schema.get("enum"):
            return schema["enum"][0]

        if "allOf" in schema:
            merged: dict[str, Any] = {"type": "object", "properties": {}}
            for item in schema.get("allOf", []):
                resolved = self._dereference_schema(item, spec, depth + 1)
                if resolved.get("properties"):
                    merged["properties"].update(resolved["properties"])
            return self._schema_to_example(merged, spec, depth + 1)

        for union_key in ("oneOf", "anyOf"):
            if schema.get(union_key):
                return self._schema_to_example(schema[union_key][0], spec, depth + 1)

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

    async def _execute_operations(
        self,
        operations: list[dict[str, Any]],
        *,
        base_url: str,
        auth_info: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Execute operations with generated examples and return redacted evidence."""
        if self._is_placeholder_base_url(base_url):
            return [
                self._blocked_evidence(operation, f"placeholder base URL {base_url!r} cannot be executed")
                for operation in operations
            ]

        try:
            import httpx
        except ImportError:
            return [self._blocked_evidence(operation, "httpx is not installed") for operation in operations]

        credentials = self._load_execution_credentials()
        auth_headers, auth_query, auth_cookies = self._auth_request_parts(auth_info, credentials)
        timeout = self._execution_timeout()
        concurrency = self._execution_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:

            async def execute(operation: dict[str, Any]) -> dict[str, Any]:
                async with semaphore:
                    prepared = self._prepare_request(operation, base_url, auth_headers, auth_query, auth_cookies)
                    if prepared.get("blocked"):
                        return self._blocked_evidence(operation, prepared["reason"])
                    request_info = prepared["request"]
                    try:
                        request_kwargs = {
                            "headers": request_info["headers"],
                            "params": request_info["query"],
                            "json": request_info.get("json"),
                        }
                        if request_info.get("cookies"):
                            request_kwargs["cookies"] = request_info["cookies"]
                        response = await client.request(operation["method"], request_info["url"], **request_kwargs)
                        body = self._response_body_sample(response)
                        redacted = self._redact_value(
                            {
                                "operation_id": operation.get("operation_id", ""),
                                "method": operation["method"],
                                "path": operation["path"],
                                "status": "executed",
                                "request": request_info,
                                "response": {
                                    "status_code": response.status_code,
                                    "headers": dict(response.headers),
                                    "body": body,
                                },
                            },
                            credentials,
                        )
                        return redacted
                    except Exception as exc:
                        return self._redact_value(
                            {
                                "operation_id": operation.get("operation_id", ""),
                                "method": operation["method"],
                                "path": operation["path"],
                                "status": "failed",
                                "request": request_info,
                                "error": str(exc),
                            },
                            credentials,
                        )

            return list(await asyncio.gather(*(execute(operation) for operation in operations)))

    def _is_placeholder_base_url(self, base_url: str) -> bool:
        parsed = urlparse(base_url)
        host = parsed.hostname or ""
        return host in {"api.example.com", "example.com", "example.org", "example.net"} or host.endswith(".example.test")

    def _execution_timeout(self) -> float:
        try:
            return max(0.5, float(os.environ.get("OPENAPI_IMPORT_EXECUTION_TIMEOUT", "3")))
        except ValueError:
            return 3.0

    def _execution_concurrency(self) -> int:
        try:
            return max(1, int(os.environ.get("OPENAPI_IMPORT_EXECUTION_CONCURRENCY", "5")))
        except ValueError:
            return 5

    def _load_execution_credentials(self) -> dict[str, str]:
        credentials = {
            key: value
            for key, value in os.environ.items()
            if key in {"API_TOKEN", "API_KEY", "API_USER", "API_PASS"}
            or any(pattern in key for pattern in ["_USERNAME", "_PASSWORD", "_EMAIL", "_TOKEN", "_API_KEY", "_SECRET"])
        }
        try:
            from sqlmodel import Session

            from orchestrator.api.credentials import get_merged_credentials
            from orchestrator.api.db import engine

            with Session(engine) as session:
                credentials.update(get_merged_credentials(self.project_id or "default", session))
        except Exception as exc:
            logger.debug("Could not load project credentials for OpenAPI execution: %s", exc)
        return credentials

    def _auth_request_parts(
        self,
        auth_info: dict[str, Any] | None,
        credentials: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        headers: dict[str, str] = {}
        query: dict[str, str] = {}
        cookies: dict[str, str] = {}
        if not auth_info:
            return headers, query, cookies

        if auth_info["type"] == "Bearer":
            token = credentials.get(auth_info.get("env_var", "API_TOKEN")) or os.environ.get("API_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif auth_info["type"] == "API Key":
            key = credentials.get(auth_info.get("env_var", "API_KEY")) or os.environ.get("API_KEY")
            if key:
                location = auth_info.get("location", "header")
                name = auth_info.get("name", "X-API-Key")
                if location == "query":
                    query[name] = key
                elif location == "cookie":
                    cookies[name] = key
                else:
                    headers[name] = key
        elif auth_info["type"] == "Basic":
            user = credentials.get(auth_info.get("env_var_user", "API_USER")) or os.environ.get("API_USER")
            password = credentials.get(auth_info.get("env_var_pass", "API_PASS")) or os.environ.get("API_PASS")
            if user and password:
                import base64

                headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        return headers, query, cookies

    def _prepare_request(
        self,
        operation: dict[str, Any],
        base_url: str,
        auth_headers: dict[str, str],
        auth_query: dict[str, str],
        auth_cookies: dict[str, str],
    ) -> dict[str, Any]:
        path = operation["path"]
        query: dict[str, Any] = dict(auth_query)
        headers: dict[str, str] = dict(auth_headers)
        cookies: dict[str, str] = dict(auth_cookies)

        for raw_param in operation.get("parameters", []):
            param = raw_param
            if isinstance(param, dict) and "$ref" in param:
                param = self._resolve_ref(param["$ref"], operation.get("_root_spec", {})) or param
            if not isinstance(param, dict):
                continue
            location = param.get("in")
            name = param.get("name")
            if not name or location not in {"path", "query", "header", "cookie"}:
                continue
            required = bool(param.get("required")) or location == "path"
            value = self._parameter_example(param)
            if value is None:
                if required:
                    return {"blocked": True, "reason": f"missing required {location} parameter '{name}'"}
                continue
            if location == "path":
                path = path.replace("{" + name + "}", str(value))
            elif location == "query":
                query[name] = value
            elif location == "header":
                headers[name] = str(value)
            elif location == "cookie":
                cookies[name] = str(value)

        if re.search(r"\{[^}/]+\}", path):
            missing = ", ".join(re.findall(r"\{([^}/]+)\}", path))
            return {"blocked": True, "reason": f"missing required path parameter(s): {missing}"}

        request_body = None
        if operation.get("request_body") is not None:
            request_body = operation.get("request_body")
        elif operation.get("request_body_required"):
            return {"blocked": True, "reason": "missing required JSON request body example"}

        return {
            "request": {
                "url": self._join_url(base_url, path),
                "path": path,
                "query": query,
                "headers": headers,
                "cookies": cookies,
                "json": request_body,
            }
        }

    def _join_url(self, base_url: str, path: str) -> str:
        return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))

    def _parameter_example(self, parameter: dict[str, Any]) -> Any:
        if "example" in parameter:
            return parameter["example"]
        examples = parameter.get("examples")
        if isinstance(examples, dict) and examples:
            first = next(iter(examples.values()))
            if isinstance(first, dict) and "value" in first:
                return first["value"]
        schema = parameter.get("schema", {})
        if not isinstance(schema, dict):
            return None
        return self._example_from_schema(schema)

    def _example_from_schema(self, schema: dict[str, Any]) -> Any:
        if not isinstance(schema, dict):
            return None
        if "example" in schema:
            return schema["example"]
        if "default" in schema:
            return schema["default"]
        if schema.get("enum"):
            return schema["enum"][0]
        schema_type = schema.get("type")
        if schema_type == "string":
            fmt = schema.get("format")
            if fmt == "email":
                return "test@example.com"
            if fmt == "date-time":
                return "2024-01-01T00:00:00Z"
            if fmt == "uuid":
                return "550e8400-e29b-41d4-a716-446655440000"
            return "string"
        if schema_type == "integer":
            return 1
        if schema_type == "number":
            return 1.0
        if schema_type == "boolean":
            return True
        if schema_type == "array":
            item = self._example_from_schema(schema.get("items", {}))
            return [item] if item is not None else []
        if schema_type == "object" or schema.get("properties"):
            return {
                name: self._example_from_schema(prop_schema)
                for name, prop_schema in schema.get("properties", {}).items()
                if self._example_from_schema(prop_schema) is not None
            }
        return None

    def _blocked_evidence(self, operation: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "operation_id": operation.get("operation_id", ""),
            "method": operation["method"],
            "path": operation["path"],
            "status": "blocked",
            "reason": reason,
        }

    def _response_body_sample(self, response: Any) -> Any:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except Exception:
                pass
        text = response.text
        return text[:4000] if isinstance(text, str) else text

    def _redact_value(self, value: Any, credentials: dict[str, str]) -> Any:
        secret_values = [secret for secret in credentials.values() if secret]
        sensitive_keys = {"authorization", "cookie", "set-cookie", "x-api-key", "api_key", "token", "password", "secret"}
        if isinstance(value, dict):
            redacted = {}
            for key, child in value.items():
                if str(key).lower() in sensitive_keys or any(part in str(key).lower() for part in sensitive_keys):
                    redacted[key] = "<redacted>"
                else:
                    redacted[key] = self._redact_value(child, credentials)
            return redacted
        if isinstance(value, list):
            return [self._redact_value(item, credentials) for item in value]
        if isinstance(value, str):
            redacted_text = value
            for secret in secret_values:
                redacted_text = redacted_text.replace(secret, "<redacted>")
            return redacted_text
        return value

    def _write_evidence(self, slug: str, evidence: list[dict[str, Any]]) -> Path:
        evidence_dir = self.specs_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / f"{slug}-evidence.json"
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        return evidence_path

    def _analyze_evidence(self, operations: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        by_key = {(item["method"], item["path"]): item for item in evidence}
        operation_analysis = []
        for operation in operations:
            item = by_key.get((operation["method"], operation["path"]), {})
            assertions = []
            response_shape = None
            if item.get("status") == "executed":
                status_code = item.get("response", {}).get("status_code")
                assertions.append(f"response status is {status_code}")
                body = item.get("response", {}).get("body")
                response_shape = self._infer_shape(body)
                if isinstance(body, dict):
                    for field in list(body.keys())[:8]:
                        assertions.append(f"response body has property `{field}`")
                elif isinstance(body, list):
                    assertions.append("response body is an array")
            elif item.get("status") == "blocked":
                assertions.append(f"blocked: {item.get('reason')}")
            elif item.get("status") == "failed":
                assertions.append(f"request failed: {item.get('error')}")
            operation_analysis.append(
                {
                    "method": operation["method"],
                    "path": operation["path"],
                    "status": item.get("status", "missing"),
                    "assertions": assertions,
                    "response_shape": response_shape,
                }
            )
        return {"operations": operation_analysis}

    def _infer_shape(self, value: Any, depth: int = 0) -> Any:
        if depth > 4:
            return "..."
        if isinstance(value, dict):
            return {key: self._infer_shape(child, depth + 1) for key, child in list(value.items())[:20]}
        if isinstance(value, list):
            return [self._infer_shape(value[0], depth + 1)] if value else []
        if value is None:
            return "null"
        return type(value).__name__

    def _dereference_schema(self, schema: dict, spec: dict, depth: int = 0) -> dict:
        """Resolve local refs for one schema without expanding the whole spec."""
        if not isinstance(schema, dict) or depth > 8:
            return {}
        if "$ref" in schema:
            resolved = self._resolve_ref(schema["$ref"], spec)
            return self._dereference_schema(resolved or {}, spec, depth + 1)
        result: dict[str, Any] = {}
        for key, value in schema.items():
            if isinstance(value, dict):
                result[key] = self._dereference_schema(value, spec, depth + 1)
            elif isinstance(value, list):
                result[key] = [
                    self._dereference_schema(item, spec, depth + 1) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def _schemas_for_operation(self, spec: dict, path_item: dict, operation: dict) -> dict[str, dict]:
        """Return only component/definition schemas reachable from one operation."""
        refs: set[str] = set()
        containers = [
            *path_item.get("parameters", []),
            *operation.get("parameters", []),
            operation.get("requestBody", {}),
            operation.get("responses", {}),
        ]
        for container in containers:
            self._collect_local_refs(container, refs)

        resolved: dict[str, dict] = {}
        pending = list(refs)
        while pending:
            ref = pending.pop()
            schema = self._resolve_ref(ref, spec)
            if not schema:
                continue
            if self._is_schema_ref(ref):
                if ref in resolved:
                    continue
                resolved[ref] = schema
            nested_refs: set[str] = set()
            self._collect_local_refs(schema, nested_refs)
            pending.extend(sorted(nested_refs - refs))
            refs.update(nested_refs)
        return resolved

    def _collect_local_refs(self, value: Any, refs: set[str]) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/"):
                refs.add(ref)
            for child in value.values():
                self._collect_local_refs(child, refs)
        elif isinstance(value, list):
            for item in value:
                self._collect_local_refs(item, refs)

    def _is_schema_ref(self, ref: str) -> bool:
        return ref.startswith("#/components/schemas/") or ref.startswith("#/definitions/")

    def _resolve_ref(self, ref_path: str, spec: dict) -> dict | None:
        """Resolve a $ref path in the spec."""
        if not ref_path.startswith("#/"):
            return None

        parts = ref_path[2:].split("/")
        current = spec
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
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

    def _generate_evidence_spec(
        self,
        group_name: str,
        endpoints: list[dict],
        base_url: str,
        auth_info: dict | None,
        evidence: list[dict[str, Any]],
        analysis: dict[str, Any],
        evidence_path: Path | None,
    ) -> Path:
        """Generate a markdown API spec backed by observed HTTP evidence."""
        slug = self._slugify(group_name)
        spec_path = self.specs_dir / f"{slug}.md"
        evidence_by_key = {(item["method"], item["path"]): item for item in evidence}
        analysis_by_key = {(item["method"], item["path"]): item for item in analysis.get("operations", [])}
        executed = sum(1 for item in evidence if item.get("status") == "executed")
        blocked = sum(1 for item in evidence if item.get("status") == "blocked")
        failed = sum(1 for item in evidence if item.get("status") == "failed")

        lines = [
            f"# Test: {group_name.title()} API Evidence",
            "",
            "## Type: API",
            f"## Base URL: {base_url}",
        ]

        if auth_info:
            if auth_info["type"] == "Bearer":
                lines.append(f"## Auth: Bearer {{{{{auth_info['env_var']}}}}}")
            elif auth_info["type"] == "API Key":
                lines.append(f"## Auth: {auth_info['name']}: {{{{{auth_info['env_var']}}}}}")
            elif auth_info["type"] == "Basic":
                lines.append("## Auth: Basic {{API_USER}}/{{API_PASS}}")

        if evidence_path:
            try:
                lines.append(f"## Evidence: {evidence_path.relative_to(BASE_DIR)}")
            except ValueError:
                lines.append(f"## Evidence: {evidence_path}")

        lines.extend(
            [
                "",
                "## Purpose",
                (
                    f"Evidence-backed API coverage for {len(endpoints)} documented operation(s). "
                    f"Executed {executed}, blocked {blocked}, failed {failed}."
                ),
                "",
                "## Setup Notes",
                "- Request and response evidence is redacted before it is written to disk.",
                "- Mutating methods may have been executed while collecting evidence.",
                "- Blocked operations need concrete path, query, auth, or body values before tests can be reliable.",
                "",
                "## Endpoints",
            ]
        )

        for endpoint in endpoints:
            key = (endpoint["method"], endpoint["path"])
            item = evidence_by_key.get(key, {})
            analyzed = analysis_by_key.get(key, {})
            lines.extend(["", f"### {endpoint['method']} {endpoint['path']}"])
            if endpoint.get("operation_id"):
                lines.append(f"- Operation ID: `{endpoint['operation_id']}`")
            if endpoint.get("summary"):
                lines.append(f"- Summary: {endpoint['summary']}")
            if endpoint.get("description"):
                lines.append(f"- Description: {endpoint['description']}")

            request = item.get("request", {})
            if request:
                lines.append("- Request example:")
                lines.append("```json")
                lines.append(json.dumps(self._compact_request_example(request), indent=2, sort_keys=True))
                lines.append("```")

            if item.get("status") == "executed":
                response = item.get("response", {})
                lines.append(f"- Observed status: `{response.get('status_code')}`")
                lines.append("- Response sample:")
                lines.append("```json")
                lines.append(json.dumps(response.get("body"), indent=2, sort_keys=True))
                lines.append("```")
                if analyzed.get("response_shape") is not None:
                    lines.append("- Inferred response shape:")
                    lines.append("```json")
                    lines.append(json.dumps(analyzed["response_shape"], indent=2, sort_keys=True))
                    lines.append("```")
            elif item.get("status") == "blocked":
                lines.append(f"- Blocked: {item.get('reason')}")
            elif item.get("status") == "failed":
                lines.append(f"- Execution failed: {item.get('error')}")

            assertions = analyzed.get("assertions") or []
            if assertions:
                lines.append("- Testable assertions:")
                for assertion in assertions:
                    lines.append(f"  - {assertion}")

            documented_codes = ", ".join(str(code) for code in endpoint.get("responses", {}).keys()) or "none"
            lines.append(f"- Documented response codes: {documented_codes}")

        lines.extend(["", "## Steps"])
        step_num = 1
        for endpoint in endpoints:
            item = evidence_by_key.get((endpoint["method"], endpoint["path"]), {})
            if item.get("status") != "executed":
                continue
            request = item.get("request", {})
            step = f"{step_num}. {endpoint['method']} {endpoint['path']}"
            if request.get("json") is not None:
                step += f" with body {json.dumps(request['json'], sort_keys=True)}"
            lines.append(step)
            step_num += 1
            status_code = item.get("response", {}).get("status_code")
            lines.append(f"{step_num}. Verify response status is {status_code}")
            step_num += 1
            body = item.get("response", {}).get("body")
            if isinstance(body, dict):
                for field in list(body.keys())[:3]:
                    lines.append(f"{step_num}. Verify response body has property \"{field}\"")
                    step_num += 1

        lines.extend(["", "## Expected Outcome"])
        lines.append("- Executed operations continue to return the observed status codes and response shapes.")
        if blocked:
            lines.append("- Blocked operations are resolved with valid example inputs before generating final tests.")
        if failed:
            lines.append("- Failed operations are reviewed as endpoint or environment failures, not import failures.")

        spec_path.write_text("\n".join(lines), encoding="utf-8")
        return spec_path

    def _compact_request_example(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "url": request.get("url"),
            "query": request.get("query") or {},
            "headers": request.get("headers") or {},
            "cookies": request.get("cookies") or {},
            "json": request.get("json"),
        }

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

    def _generate_plan(
        self,
        plan_items: list[dict[str, Any]],
        *,
        base_url: str,
        feature_filter: str | None,
        method_filter: list[str],
    ) -> Path:
        """Generate a reviewable OpenAPI import test plan."""
        method_label = ", ".join(method_filter) if method_filter else "all documented methods"
        filter_label = feature_filter or "none"
        slug_parts = ["openapi-plan"]
        if method_filter:
            slug_parts.extend(method.lower() for method in method_filter)
        if feature_filter:
            slug_parts.append(self._slugify(feature_filter))
        plan_path = self.specs_dir / f"{self._slugify('-'.join(slug_parts))}.md"

        lines = [
            "# OpenAPI Import Test Plan",
            "",
            "## Scope",
            f"- Base URL: {base_url}",
            f"- Method filter: {method_label}",
            f"- Feature filter: {filter_label}",
            f"- Matched operations: {len(plan_items)}",
            "",
            "## Planned API Checks",
        ]

        for item in plan_items:
            label = f"{item['method']} {item['path']}"
            if item.get("operation_id"):
                label += f" ({item['operation_id']})"
            lines.append(f"- [{item['id']}] {label}")
            if item.get("summary"):
                lines.append(f"  - Summary: {item['summary']}")
            lines.append(f"  - Expected status: {item['success_status']}")
            lines.append(f"  - Request body: {'yes' if item['has_request_body'] else 'no'}")

        lines.extend(
            [
                "",
                "## Review Notes",
                "- Confirm required authentication values before running generated tests.",
                "- Replace generated placeholder request values where the API requires domain-specific data.",
            ]
        )

        plan_path.write_text("\n".join(lines))
        return plan_path

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

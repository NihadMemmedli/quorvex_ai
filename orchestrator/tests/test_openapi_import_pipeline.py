import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-api-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.workflows import openapi_processor as openapi_module
from orchestrator.workflows.openapi_processor import OpenApiProcessor


class _EvidenceHandler(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *_args):
        return

    def _read_body(self):
        length = int(self.headers.get("content-length", "0") or 0)
        if not length:
            return None
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, status: int = 200):
        body = self._read_body()
        auth = self.headers.get("authorization")
        self.__class__.seen.append({"method": self.command, "path": self.path, "body": body, "auth": auth})
        self._send_json(status, {"method": self.command, "path": self.path, "body": body, "auth": auth, "ok": True})

    def do_GET(self):
        self._handle(200)

    def do_POST(self):
        self._handle(201)

    def do_PUT(self):
        self._handle(200)

    def do_PATCH(self):
        self._handle(200)

    def do_DELETE(self):
        self._handle(204)


class _SwaggerDocsHandler(BaseHTTPRequestHandler):
    openapi_doc: dict = {}
    seen: list[dict] = []

    def log_message(self, *_args):
        return

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("content-length", "0") or 0)
        if not length:
            return None
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _record_endpoint(self, status: int):
        self.__class__.seen.append({"method": self.command, "path": self.path, "body": self._read_body()})
        self._send_json(status, {"method": self.command, "path": self.path, "ok": True})

    def do_GET(self):
        if self.path == "/docs":
            body = b"<!doctype html><script>SwaggerUIBundle({ url: '/openapi.json' })</script>"
            self.send_response(200)
            self.send_header("content-type", "text/html")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/openapi.json":
            self._send_json(200, self.__class__.openapi_doc)
            return
        self._record_endpoint(200)

    def do_POST(self):
        self._record_endpoint(201)

    def do_PUT(self):
        self._record_endpoint(200)

    def do_PATCH(self):
        self._record_endpoint(200)

    def do_DELETE(self):
        self._record_endpoint(200)


@pytest.fixture()
def evidence_server():
    _EvidenceHandler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EvidenceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", _EvidenceHandler.seen
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture()
def swagger_docs_server():
    _SwaggerDocsHandler.seen = []
    _SwaggerDocsHandler.openapi_doc = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SwaggerDocsHandler)
    base_url = f"http://127.0.0.1:{server.server_port}"
    _SwaggerDocsHandler.openapi_doc = {
        "openapi": "3.0.0",
        "servers": [{"url": base_url}],
        "paths": {
            "/items": {
                "get": {"operationId": "listItems", "responses": {"200": {"description": "ok"}}},
                "post": {
                    "operationId": "createItem",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                },
                "put": {"operationId": "replaceItems", "responses": {"200": {"description": "ok"}}},
                "patch": {"operationId": "patchItems", "responses": {"200": {"description": "ok"}}},
                "delete": {"operationId": "deleteItems", "responses": {"200": {"description": "deleted"}}},
            }
        },
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{base_url}/docs", _SwaggerDocsHandler.seen
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture()
def processor(tmp_path, monkeypatch):
    monkeypatch.setattr(openapi_module, "BASE_DIR", tmp_path)
    proc = OpenApiProcessor(project_id="default")
    proc.specs_dir = tmp_path / "specs" / "generated" / "api"
    proc.specs_dir.mkdir(parents=True, exist_ok=True)
    proc.api_generator.tests_dir = tmp_path / "tests" / "generated"
    proc.api_generator.tests_dir.mkdir(parents=True, exist_ok=True)
    return proc


def test_openapi3_method_filter_selects_only_post_operations(processor):
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/users": {
                "get": {"operationId": "listUsers", "responses": {"200": {"description": "ok"}}},
                "post": {"operationId": "createUser", "responses": {"201": {"description": "created"}}},
            },
            "/users/{id}": {
                "patch": {"operationId": "updateUser", "responses": {"200": {"description": "ok"}}},
            },
        },
    }

    operations = processor._index_operations(spec, "OpenAPI 3.0.0")
    matched, skipped = processor._filter_operations(operations, method_filter=["POST"])

    assert [(op["method"], op["path"]) for op in matched] == [("POST", "/users")]
    assert len(skipped) == 2
    assert {item["reason"] for item in skipped} == {"method_filter"}


def test_swagger_ui_docs_url_resolves_to_openapi_json(processor):
    html = """
    <!doctype html>
    <div id="swagger-ui"></div>
    <script>
      SwaggerUIBundle({ url: '/openapi.json', dom_id: '#swagger-ui' });
    </script>
    """

    assert (
        processor._extract_swagger_ui_spec_url(html, "http://localhost:8001/docs")
        == "http://localhost:8001/openapi.json"
    )


def test_swagger2_method_and_feature_filters_combine(processor):
    spec = {
        "swagger": "2.0",
        "host": "api.example.test",
        "paths": {
            "/orders": {
                "get": {
                    "tags": ["orders"],
                    "operationId": "listOrders",
                    "responses": {"200": {"description": "ok"}},
                },
                "post": {
                    "tags": ["orders"],
                    "operationId": "createOrder",
                    "parameters": [{"in": "body", "name": "body", "schema": {"$ref": "#/definitions/OrderInput"}}],
                    "responses": {"201": {"description": "created"}},
                },
            },
            "/users": {
                "post": {
                    "tags": ["users"],
                    "operationId": "createUser",
                    "responses": {"201": {"description": "created"}},
                },
            },
        },
        "definitions": {
            "OrderInput": {
                "type": "object",
                "properties": {"sku": {"type": "string"}},
            },
        },
    }

    operations = processor._index_operations(spec, "Swagger 2.0")
    matched, skipped = processor._filter_operations(
        operations,
        feature_filter="orders",
        method_filter=["POST"],
    )

    assert [(op["method"], op["path"]) for op in matched] == [("POST", "/orders")]
    assert len(skipped) == 2
    assert {item["reason"] for item in skipped} == {"method_filter", "feature_filter"}
    assert matched[0]["request_body"] == {"sku": "string"}


def test_ref_resolution_only_collects_schemas_used_by_selected_operations(processor):
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/pets": {
                "post": {
                    "operationId": "createPet",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/PetInput"}
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        }
                    },
                }
            },
            "/admin": {
                "get": {
                    "operationId": "adminReport",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AdminReport"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "PetInput": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
                "Pet": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "owner": {"$ref": "#/components/schemas/Owner"}},
                },
                "Owner": {
                    "type": "object",
                    "properties": {"email": {"type": "string", "format": "email"}},
                },
                "AdminReport": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                },
            }
        },
    }

    operations = processor._index_operations(spec, "OpenAPI 3.0.0")
    matched, _skipped = processor._filter_operations(operations, method_filter=["POST"])

    assert len(matched) == 1
    assert set(matched[0]["schemas"]) == {
        "#/components/schemas/PetInput",
        "#/components/schemas/Pet",
        "#/components/schemas/Owner",
    }
    assert "#/components/schemas/AdminReport" not in matched[0]["schemas"]


@pytest.mark.asyncio
async def test_huge_spec_is_chunked_before_codegen(processor, tmp_path):
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": "http://localhost:8001"}],
        "paths": {
            f"/items/{index}": {
                "post": {
                    "operationId": f"createItem{index}",
                    "responses": {"201": {"description": "created"}},
                }
            }
            for index in range(45)
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    seen_specs: list[str] = []

    async def fake_generate(spec_path: str, target_url: str | None = None, output_name: str | None = None):
        content = Path(spec_path).read_text(encoding="utf-8")
        seen_specs.append(content)
        output = processor.api_generator.tests_dir / f"{output_name}.api.spec.ts"
        output.write_text("// generated", encoding="utf-8")
        return output

    processor.api_generator.generate_test = fake_generate

    result = await processor.process_import(str(spec_path), method_filter=["POST"], mode="plan_and_tests")

    assert result.matched_operations == 45
    assert len(result.spec_paths) == 3
    assert len(result.test_paths) == 3
    assert any("split into 3 chunks" in warning for warning in result.warnings)
    assert all(content.count(". POST /items/") <= 20 for content in seen_specs)
    assert result.plan_path is not None
    assert result.plan_path.exists()


@pytest.mark.asyncio
async def test_plan_only_large_spec_chunks_without_codegen(processor, tmp_path):
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": "http://localhost:8001"}],
        "paths": {
            f"/bulk/{index}": {
                "post": {
                    "operationId": f"createBulkItem{index}",
                    "responses": {"201": {"description": "created"}},
                }
            }
            for index in range(1000)
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("plan_only must not invoke NativeApiGenerator")

    processor.api_generator.generate_test = fail_if_called

    result = await processor.process_import(str(spec_path), mode="plan_only")

    assert result.matched_operations == 1000
    assert result.chunk_count == 50
    assert result.recommended_mode == "plan_only"
    assert len(result.spec_paths) == 50
    assert result.test_paths == []
    assert result.plan_path is not None
    assert result.plan_path.exists()
    assert all(path.exists() for path in result.spec_paths)


@pytest.mark.asyncio
async def test_unfiltered_import_still_includes_all_methods(processor, tmp_path):
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/users": {
                "get": {"operationId": "listUsers", "responses": {"200": {"description": "ok"}}},
                "post": {"operationId": "createUser", "responses": {"201": {"description": "created"}}},
            },
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    async def fake_generate(spec_path: str, target_url: str | None = None, output_name: str | None = None):
        output = processor.api_generator.tests_dir / f"{output_name}.api.spec.ts"
        output.write_text("// generated", encoding="utf-8")
        return output

    processor.api_generator.generate_test = fake_generate

    result = await processor.process_import(str(spec_path), mode="plan_and_tests", base_url="http://localhost:8001")

    assert result.matched_operations == 2
    assert result.needs_input is False
    assert result.executed_operations == 0
    spec_content = result.spec_paths[0].read_text(encoding="utf-8")
    assert "GET /users" in spec_content
    assert "POST /users" in spec_content


@pytest.mark.asyncio
async def test_missing_server_url_returns_needs_input_without_artifacts(processor, tmp_path):
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/users": {
                "get": {"operationId": "listUsers", "responses": {"200": {"description": "ok"}}},
            },
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("missing base URL must not invoke NativeApiGenerator")

    processor.api_generator.generate_test = fail_if_called

    result = await processor.process_import(str(spec_path), mode="plan_and_tests")

    assert result.needs_input is True
    assert result.missing_fields == ["base_url"]
    assert result.spec_paths == []
    assert result.test_paths == []
    assert result.blocked_operations == []
    assert result.base_url is None


@pytest.mark.asyncio
async def test_placeholder_server_url_returns_needs_input_without_evidence(processor, tmp_path):
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/users": {
                "get": {"operationId": "listUsers", "responses": {"200": {"description": "ok"}}},
            },
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = await processor.process_import(str(spec_path), mode="evidence_specs")

    assert result.needs_input is True
    assert result.missing_fields == ["base_url"]
    assert result.executed_operations == 0
    assert result.evidence_paths == []
    assert result.blocked_operations == []


@pytest.mark.asyncio
async def test_evidence_specs_mode_executes_all_documented_methods(processor, tmp_path, evidence_server):
    base_url, seen = evidence_server
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": base_url}],
        "paths": {
            "/items": {
                "get": {"operationId": "listItems", "responses": {"200": {"description": "ok"}}},
                "post": {
                    "operationId": "createItem",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}, "quantity": {"type": "integer"}},
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "created"}},
                },
                "put": {"operationId": "replaceItems", "responses": {"200": {"description": "ok"}}},
                "patch": {"operationId": "patchItems", "responses": {"200": {"description": "ok"}}},
                "delete": {"operationId": "deleteItems", "responses": {"204": {"description": "deleted"}}},
            }
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("evidence_specs must not invoke NativeApiGenerator")

    processor.api_generator.generate_test = fail_if_called

    result = await processor.process_import(str(spec_path), mode="evidence_specs")

    assert result.matched_operations == 5
    assert result.executed_operations == 5
    assert result.test_paths == []
    assert {entry["method"] for entry in seen} == {"GET", "POST", "PUT", "PATCH", "DELETE"}
    content = result.spec_paths[0].read_text(encoding="utf-8")
    assert "Response sample" in content
    assert "Inferred response shape" in content
    assert "response body has property `method`" in content
    evidence = json.loads(result.evidence_paths[0].read_text(encoding="utf-8"))
    assert all(item["status"] == "executed" for item in evidence)


@pytest.mark.asyncio
async def test_swagger_docs_url_import_resolves_and_executes_operations(processor, swagger_docs_server):
    docs_url, seen = swagger_docs_server

    result = await processor.process_import(docs_url, mode="evidence_specs")

    assert result.resolved_source_url.endswith("/openapi.json")
    assert result.matched_operations == 5
    assert result.executed_operations == 5
    assert result.blocked_operations == []
    assert result.failed_operations == []
    assert {entry["method"] for entry in seen} == {"GET", "POST", "PUT", "PATCH", "DELETE"}
    assert result.evidence_paths[0].exists()
    spec_content = result.spec_paths[0].read_text(encoding="utf-8")
    assert "Evidence-backed API coverage" in spec_content
    assert "GET /items" in spec_content
    assert "POST /items" in spec_content
    assert "Response sample" in spec_content


@pytest.mark.asyncio
async def test_plan_and_tests_codegen_runs_after_api_spec_without_evidence_execution(processor, tmp_path, evidence_server):
    base_url, _seen = evidence_server
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": base_url}],
        "paths": {
            "/health": {
                "get": {"operationId": "health", "responses": {"200": {"description": "ok"}}},
            }
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    seen_specs: list[str] = []

    async def fake_generate(spec_path: str, target_url: str | None = None, output_name: str | None = None):
        content = Path(spec_path).read_text(encoding="utf-8")
        seen_specs.append(content)
        assert "Response sample" not in content
        assert "GET /health" in content
        output = processor.api_generator.tests_dir / f"{output_name}.api.spec.ts"
        output.write_text("// generated", encoding="utf-8")
        return output

    processor.api_generator.generate_test = fake_generate

    result = await processor.process_import(str(spec_path), mode="plan_and_tests")

    assert result.executed_operations == 0
    assert len(seen_specs) == 1
    assert len(result.test_paths) == 1


@pytest.mark.asyncio
async def test_auth_headers_are_redacted_from_evidence_and_specs(processor, tmp_path, monkeypatch, evidence_server):
    base_url, seen = evidence_server
    monkeypatch.setenv("API_TOKEN", "super-secret-token")
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": base_url}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            }
        },
        "security": [{"bearerAuth": []}],
        "paths": {
            "/secure": {
                "get": {"operationId": "secure", "responses": {"200": {"description": "ok"}}},
            }
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = await processor.process_import(str(spec_path), mode="evidence_specs")

    assert seen[0]["auth"] == "Bearer super-secret-token"
    evidence_text = result.evidence_paths[0].read_text(encoding="utf-8")
    spec_text = result.spec_paths[0].read_text(encoding="utf-8")
    assert "super-secret-token" not in evidence_text
    assert "super-secret-token" not in spec_text
    assert "<redacted>" in evidence_text
    assert "{{API_TOKEN}}" in spec_text


@pytest.mark.asyncio
async def test_missing_required_path_value_blocks_operation(processor, tmp_path, evidence_server):
    base_url, seen = evidence_server
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": base_url}],
        "paths": {
            "/items/{item_id}": {
                "get": {
                    "operationId": "getItem",
                    "parameters": [{"name": "item_id", "in": "path", "required": True}],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = await processor.process_import(str(spec_path), mode="evidence_specs")

    assert seen == []
    assert result.executed_operations == 0
    assert len(result.blocked_operations) == 1
    assert "missing required path parameter" in result.blocked_operations[0]["reason"]
    assert "Blocked:" in result.spec_paths[0].read_text(encoding="utf-8")

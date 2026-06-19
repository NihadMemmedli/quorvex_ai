#!/usr/bin/env python3
"""Check documentation references that commonly drift from source files."""

from __future__ import annotations

import ast
import json
import re
import struct
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


class MkDocsConfigLoader(yaml.SafeLoader):
    """Safe YAML loader that ignores MkDocs Python object tags."""


def _construct_python_name(loader: yaml.Loader, node: yaml.Node) -> str:
    return loader.construct_scalar(node)


MkDocsConfigLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:",
    lambda loader, suffix, node: suffix,
)
MkDocsConfigLoader.add_constructor(
    "tag:yaml.org,2002:python/name",
    _construct_python_name,
)

ENV_EXAMPLES = [
    REPO_ROOT / ".env.example",
    REPO_ROOT / ".env.prod.example",
]
SOURCE_ENV_PATHS = [
    REPO_ROOT / "orchestrator",
    REPO_ROOT / "web/src",
]
SOURCE_ENV_EXCLUDES = {
    "VAR_NAME",
}
ENV_DOC = REPO_ROOT / "docs/reference/environment-variables.md"
CLI_SOURCE = REPO_ROOT / "orchestrator/cli.py"
CLI_DOC = REPO_ROOT / "docs/reference/cli.md"
API_SOURCE_DIR = REPO_ROOT / "orchestrator/api"
API_DOC = REPO_ROOT / "docs/reference/api-endpoints.md"
DASHBOARD_SOURCE_DIR = REPO_ROOT / "web/src/app"
DASHBOARD_DOC = REPO_ROOT / "docs/reference/web-dashboard.md"
DOCS_DIR = REPO_ROOT / "docs"
MKDOCS_CONFIG = REPO_ROOT / "mkdocs.yml"
DOCS_UI_ASSETS_DIR = DOCS_DIR / "assets/ui"
DOCS_VISUAL_MANIFEST = DOCS_UI_ASSETS_DIR / "visual-assets.manifest.json"

API_METHODS = {"get", "post", "put", "patch", "delete"}
EXCLUDED_API_PREFIXES: tuple[str, ...] = ()

SETUP_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "README.minimal.md",
    REPO_ROOT / "CONTRIBUTING.md",
    REPO_ROOT / "docs/index.md",
    REPO_ROOT / "docs/tutorials/getting-started.md",
    REPO_ROOT / "docs/guides/deployment.md",
    REPO_ROOT / "docs/reference/faq.md",
    REPO_ROOT / "docs/guides/contributing.md",
    REPO_ROOT / "docs/guides/credential-management.md",
]

STALE_PATTERNS = {
    "Node.js 18+ prerequisite": re.compile(r"Node\.js\s+18\+|\|\s*Node\.js\s*\|\s*18\+\s*\|"),
    "copying .env.example to .env.prod": re.compile(r"cp\s+\.env\.example\s+\.env\.prod\b"),
    "legacy docker-compose command": re.compile(r"\bdocker-compose\s+"),
    "legacy credential endpoint": re.compile(r"http://localhost:8001/credentials(?:\?|\b)"),
}

DOCS_WITH_ASSETS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "README.minimal.md",
    *DOCS_DIR.rglob("*.md"),
]

LOCAL_API_EXAMPLE_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "README.minimal.md",
    *DOCS_DIR.rglob("*.md"),
]

DOC_ONLY_API_PATHS = {
    "/docs",
    "/redoc",
    "/openapi.json",
}

PUBLIC_DOC_EXCLUDES = {
    DOCS_DIR / ".style-guide.md",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def env_keys_from_examples() -> set[str]:
    keys: set[str] = set()
    env_pattern = re.compile(r"^\s*([A-Z][A-Z0-9_]+)=", re.MULTILINE)
    for path in ENV_EXAMPLES:
        keys.update(env_pattern.findall(read_text(path)))
    return keys


def env_keys_from_source() -> set[str]:
    keys: set[str] = set()
    patterns = [
        re.compile(r"os\.(?:environ\.get|getenv)\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']"),
        re.compile(r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]+)[\"']\s*]"),
        re.compile(r"process\.env\.([A-Z][A-Z0-9_]+)"),
    ]

    for root in SOURCE_ENV_PATHS:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue

            text = read_text(path)
            for pattern in patterns:
                keys.update(pattern.findall(text))

    return keys - SOURCE_ENV_EXCLUDES


def documented_env_keys() -> set[str]:
    return set(re.findall(r"`([A-Z][A-Z0-9_]+)`", read_text(ENV_DOC)))


def cli_flags_from_source() -> set[str]:
    source = read_text(CLI_SOURCE)
    tree = ast.parse(source)
    flags: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue

        has_suppressed_help = any(
            keyword.arg == "help"
            and isinstance(keyword.value, ast.Attribute)
            and isinstance(keyword.value.value, ast.Name)
            and keyword.value.value.id == "argparse"
            and keyword.value.attr == "SUPPRESS"
            for keyword in node.keywords
        )
        if has_suppressed_help:
            continue

        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("--"):
                flags.add(arg.value)

    return flags


def documented_cli_flags() -> set[str]:
    return set(re.findall(r"`(--[a-zA-Z0-9][a-zA-Z0-9-]*)`", read_text(CLI_DOC)))


def normalize_path(path: str) -> str:
    path = re.sub(r"\{([^}:]+):[^}]+\}", r"{\1}", path)
    path = re.sub(r"//+", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


def canonical_endpoint_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{param}", normalize_path(path))


def join_paths(prefix: str, path: str) -> str:
    if not prefix:
        return normalize_path(path or "/")
    if not path:
        return normalize_path(prefix)
    return normalize_path(f"{prefix.rstrip('/')}/{path.lstrip('/')}")


def constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def router_prefixes(tree: ast.AST) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if not isinstance(node.value.func, ast.Name) or node.value.func.id != "APIRouter":
            continue

        prefix = ""
        for keyword in node.value.keywords:
            if keyword.arg == "prefix":
                prefix = constant_string(keyword.value) or ""
                break

        for target in node.targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix
    return prefixes


def fastapi_routes_from_file(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(read_text(path))
    prefixes = router_prefixes(tree)
    routes: set[tuple[str, str]] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.lower()
            if method not in API_METHODS:
                continue
            if not isinstance(decorator.func.value, ast.Name):
                continue

            owner = decorator.func.value.id
            if owner == "app":
                prefix = ""
            elif owner in prefixes:
                prefix = prefixes[owner]
            else:
                continue

            route_path = constant_string(decorator.args[0]) if decorator.args else ""
            if route_path is None:
                continue
            routes.add((method.upper(), join_paths(prefix, route_path)))

    routes.update(literal_api_route_table_routes(tree))
    return routes


def literal_api_route_table_routes(tree: ast.AST) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "routes" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue

        for item in node.value.elts:
            if not isinstance(item, (ast.List, ast.Tuple)) or len(item.elts) < 2:
                continue
            method = constant_string(item.elts[0])
            route_path = constant_string(item.elts[1])
            if not method or method.lower() not in API_METHODS or route_path is None:
                continue
            routes.add((method.upper(), normalize_path(route_path)))
    return routes


def discovered_api_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for path in API_SOURCE_DIR.glob("*.py"):
        routes.update(fastapi_routes_from_file(path))
    return {route for route in routes if should_enforce_api_route(route[1])}


def should_enforce_api_route(path: str) -> bool:
    canonical = canonical_endpoint_path(path)
    if any(canonical == prefix or canonical.startswith(f"{prefix}/") for prefix in EXCLUDED_API_PREFIXES):
        return False
    return True


def documented_api_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|",
        re.MULTILINE,
    )
    for method, path in pattern.findall(read_text(API_DOC)):
        routes.add((method, normalize_path(path)))
    return routes


def route_key(route: tuple[str, str]) -> tuple[str, str]:
    method, path = route
    return method, canonical_endpoint_path(path)


def canonical_doc_example_path(path: str) -> str:
    parts = [part for part in normalize_path(path).split("/") if part]
    canonical_parts: list[str] = []

    for index, part in enumerate(parts):
        previous = parts[index - 1] if index else ""
        before_previous = parts[index - 2] if index >= 2 else ""
        is_placeholder = (
            re.fullmatch(r"[A-Z][A-Z0-9_]*", part) is not None
            or re.fullmatch(r"\d+", part) is not None
            or part.startswith("your-")
            or (previous == "projects" and part == "default")
            or (before_previous == "rtm" and previous == "export" and part in {"csv", "html", "markdown", "json"})
        )
        canonical_parts.append("{param}" if is_placeholder else part)

    return canonical_endpoint_path("/" + "/".join(canonical_parts))


def documented_local_api_examples() -> list[tuple[Path, str, str]]:
    examples: list[tuple[Path, str, str]] = []
    pattern = re.compile(r"http://localhost:8001([^\s`\"<>)]*)")
    for doc in LOCAL_API_EXAMPLE_DOCS:
        text = read_text(doc)
        for match in pattern.finditer(text):
            raw = match.group(1).rstrip(".,")
            path = normalize_path(unquote(urlsplit(raw).path))
            if path in DOC_ONLY_API_PATHS or not path or path == "/":
                continue
            examples.append((doc, path, canonical_doc_example_path(path)))
    return examples


def dashboard_route_from_page(path: Path) -> str | None:
    relative = path.relative_to(DASHBOARD_SOURCE_DIR)
    parts = list(relative.parts[:-1])
    visible_parts: list[str] = []

    for part in parts:
        if part.startswith("(") and part.endswith(")"):
            continue
        if part.startswith("[...") and part.endswith("]"):
            visible_parts.append("{" + part[4:-1] + "}")
        elif part.startswith("[") and part.endswith("]"):
            visible_parts.append("{" + part[1:-1] + "}")
        else:
            visible_parts.append(part)

    route = "/" + "/".join(visible_parts)
    return normalize_path(route)


def discovered_dashboard_routes() -> set[str]:
    return {
        route
        for page in DASHBOARD_SOURCE_DIR.rglob("page.*")
        if page.suffix in {".tsx", ".ts", ".jsx", ".js"}
        if (route := dashboard_route_from_page(page)) is not None
    }


def documented_dashboard_routes() -> set[str]:
    text = read_text(DASHBOARD_DOC)
    return {normalize_path(path) for path in re.findall(r"\|\s*[^|\n]+\|\s*`(/[^`]*)`\s*\|", text)}


def check_env_docs() -> list[str]:
    missing = sorted((env_keys_from_examples() | env_keys_from_source()) - documented_env_keys())
    if not missing:
        return []
    return [
        "docs/reference/environment-variables.md is missing environment variables from examples or source: "
        + ", ".join(missing)
    ]


def check_cli_docs() -> list[str]:
    missing = sorted(cli_flags_from_source() - documented_cli_flags())
    if not missing:
        return []
    return ["docs/reference/cli.md is missing CLI flags from orchestrator/cli.py: " + ", ".join(missing)]


def check_stale_setup_docs() -> list[str]:
    errors: list[str] = []
    for path in SETUP_DOCS:
        text = read_text(path)
        relative = path.relative_to(REPO_ROOT)
        for label, pattern in STALE_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                errors.append(f"{relative} contains stale setup guidance: {label}")
    return errors


def check_api_docs() -> list[str]:
    documented = {route_key(route) for route in documented_api_routes()}
    missing = sorted(
        route for route in discovered_api_routes() if route_key(route) not in documented
    )
    if not missing:
        return []

    formatted = ", ".join(f"{method} {path}" for method, path in missing)
    return ["docs/reference/api-endpoints.md is missing selected public API routes: " + formatted]


def check_local_api_examples() -> list[str]:
    discovered_paths = {route_key(route)[1] for route in discovered_api_routes()}
    missing: list[str] = []
    for doc, path, canonical in documented_local_api_examples():
        if canonical not in discovered_paths:
            missing.append(f"{doc.relative_to(REPO_ROOT)} references http://localhost:8001{path}")

    if not missing:
        return []
    return ["docs contain localhost API examples for unknown routes: " + "; ".join(sorted(set(missing)))]


def check_dashboard_docs() -> list[str]:
    documented = {canonical_endpoint_path(path) for path in documented_dashboard_routes()}
    missing = sorted(
        route for route in discovered_dashboard_routes() if canonical_endpoint_path(route) not in documented
    )
    if not missing:
        return []
    return ["docs/reference/web-dashboard.md is missing dashboard routes: " + ", ".join(missing)]


def nav_docs_from_mkdocs() -> set[Path]:
    config = yaml.load(read_text(MKDOCS_CONFIG), Loader=MkDocsConfigLoader)
    docs: set[Path] = set()

    def walk_nav(item: object) -> None:
        if isinstance(item, str) and item.endswith(".md"):
            docs.add((DOCS_DIR / item).resolve())
        elif isinstance(item, list):
            for child in item:
                walk_nav(child)
        elif isinstance(item, dict):
            for child in item.values():
                walk_nav(child)

    walk_nav(config.get("nav", []))
    return docs


def public_docs() -> set[Path]:
    return {
        path.resolve()
        for path in DOCS_DIR.rglob("*.md")
        if path not in PUBLIC_DOC_EXCLUDES and not path.name.startswith(".")
    }


def check_nav_docs() -> list[str]:
    missing = sorted(path.relative_to(DOCS_DIR) for path in public_docs() - nav_docs_from_mkdocs())
    if not missing:
        return []
    return ["mkdocs.yml nav is missing public docs pages: " + ", ".join(map(str, missing))]


def local_asset_path(markdown_file: Path, raw_target: str) -> Path | None:
    if raw_target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    parsed = urlsplit(raw_target)
    if parsed.scheme or not parsed.path:
        return None
    decoded = unquote(parsed.path)
    if markdown_file == REPO_ROOT / "README.md" or markdown_file == REPO_ROOT / "README.minimal.md":
        return (REPO_ROOT / decoded).resolve()
    return (markdown_file.parent / decoded).resolve()


def referenced_assets(markdown_file: Path) -> set[Path]:
    text = read_text(markdown_file)
    targets = set(re.findall(r"!\[[^\]]*]\(([^)]+)\)", text))
    targets.update(re.findall(r"<img\s+[^>]*src=[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE))
    return {
        asset
        for target in targets
        if (asset := local_asset_path(markdown_file, target.strip())) is not None
    }


def referenced_image_assets(markdown_file: Path) -> list[tuple[str, Path]]:
    text = read_text(markdown_file)
    references: list[tuple[str, Path]] = []

    for alt, target in re.findall(r"!\[([^\]]*)]\(([^)]+)\)", text):
        asset = local_asset_path(markdown_file, target.strip())
        if asset is not None:
            references.append((alt.strip(), asset))

    image_tag_pattern = re.compile(r"<img\s+([^>]+)>", flags=re.IGNORECASE)
    src_pattern = re.compile(r"\bsrc=[\"']([^\"']+)[\"']", flags=re.IGNORECASE)
    alt_pattern = re.compile(r"\balt=[\"']([^\"']*)[\"']", flags=re.IGNORECASE)
    for match in image_tag_pattern.finditer(text):
        attrs = match.group(1)
        src = src_pattern.search(attrs)
        if not src:
            continue
        asset = local_asset_path(markdown_file, src.group(1).strip())
        if asset is not None:
            alt = alt_pattern.search(attrs)
            references.append(((alt.group(1).strip() if alt else ""), asset))

    return references


def check_doc_assets() -> list[str]:
    missing: list[str] = []
    for doc in DOCS_WITH_ASSETS:
        if not doc.exists():
            continue
        for asset in sorted(referenced_assets(doc)):
            if not asset.exists():
                missing.append(f"{doc.relative_to(REPO_ROOT)} references missing asset {asset.relative_to(REPO_ROOT)}")
    if not missing:
        return []
    return ["missing local documentation assets: " + "; ".join(missing)]


def is_docs_ui_asset(path: Path) -> bool:
    try:
        path.relative_to(DOCS_UI_ASSETS_DIR.resolve())
    except ValueError:
        return False
    return path.suffix.lower() in {".png", ".gif", ".webm"}


def image_dimensions(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as handle:
        header = handle.read(32)

    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
        return struct.unpack(">II", header[16:24])

    if header[:6] in {b"GIF87a", b"GIF89a"} and len(header) >= 10:
        return struct.unpack("<HH", header[6:10])

    return None


def check_docs_visual_coverage() -> list[str]:
    errors: list[str] = []
    for doc in sorted(public_docs()):
        visual_refs = [
            (alt, asset)
            for alt, asset in referenced_image_assets(doc)
            if is_docs_ui_asset(asset)
        ]
        if not visual_refs:
            errors.append(f"{doc.relative_to(REPO_ROOT)} does not render a docs UI screenshot or GIF")
            continue

        missing_alt = [
            asset.relative_to(REPO_ROOT)
            for alt, asset in visual_refs
            if not alt
        ]
        if missing_alt:
            errors.append(
                f"{doc.relative_to(REPO_ROOT)} has docs UI visuals without alt text: "
                + ", ".join(map(str, missing_alt))
            )

    if not errors:
        return []
    return ["documentation UI visual coverage failed: " + "; ".join(errors)]


def check_docs_visual_manifest() -> list[str]:
    if not DOCS_VISUAL_MANIFEST.exists():
        return [f"{DOCS_VISUAL_MANIFEST.relative_to(REPO_ROOT)} is missing"]

    manifest = json.loads(read_text(DOCS_VISUAL_MANIFEST))
    assets = manifest.get("assets", [])
    errors: list[str] = []
    seen_ids: set[str] = set()

    for entry in assets:
        asset_id = entry.get("id")
        asset_path_value = entry.get("path")
        alt = str(entry.get("alt") or "").strip()
        if not asset_id or asset_id in seen_ids:
            errors.append(f"visual manifest contains missing or duplicate asset id: {asset_id!r}")
            continue
        seen_ids.add(asset_id)

        if not asset_path_value:
            errors.append(f"visual manifest asset {asset_id} is missing a path")
            continue

        asset_path = (REPO_ROOT / asset_path_value).resolve()
        if not is_docs_ui_asset(asset_path):
            errors.append(f"visual manifest asset {asset_id} is outside docs/assets/ui")
            continue
        if not asset_path.exists():
            errors.append(f"visual manifest asset {asset_id} is missing {asset_path.relative_to(REPO_ROOT)}")
            continue
        if asset_path.stat().st_size == 0:
            errors.append(f"visual manifest asset {asset_id} is empty")
            continue
        if not alt:
            errors.append(f"visual manifest asset {asset_id} is missing alt text")

        if asset_path.suffix.lower() in {".png", ".gif"}:
            dimensions = image_dimensions(asset_path)
            if dimensions is None:
                errors.append(f"visual manifest asset {asset_id} is not a valid PNG/GIF")
            elif dimensions[0] < 320 or dimensions[1] < 180:
                errors.append(
                    f"visual manifest asset {asset_id} is too small: {dimensions[0]}x{dimensions[1]}"
                )

    if not errors:
        return []
    return ["documentation UI visual manifest failed: " + "; ".join(errors)]


def check_docs_visuals() -> list[str]:
    return check_docs_visual_manifest() + check_docs_visual_coverage()


def main() -> int:
    if "--visual-only" in sys.argv:
        errors = check_docs_visuals()
        if errors:
            for error in errors:
                print(f"[docs-drift] ERROR: {error}", file=sys.stderr)
            return 1

        print("[docs-drift] OK")
        return 0

    errors = (
        check_env_docs()
        + check_cli_docs()
        + check_stale_setup_docs()
        + check_api_docs()
        + check_local_api_examples()
        + check_dashboard_docs()
        + check_nav_docs()
        + check_doc_assets()
        + check_docs_visuals()
    )
    if errors:
        for error in errors:
            print(f"[docs-drift] ERROR: {error}", file=sys.stderr)
        return 1

    print("[docs-drift] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

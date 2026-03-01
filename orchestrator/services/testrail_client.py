"""
TestRail API Client - Async HTTP client for TestRail REST API v2.

Provides methods for managing projects, suites, sections, and cases.
Uses httpx.AsyncClient with rate limiting and retry logic.
"""

import asyncio
import logging
from typing import Any

import httpx
from circuitbreaker import circuit
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class TestrailError(Exception):
    """Base exception for TestRail API errors."""

    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


class TestrailClient:
    """Async TestRail API client with rate limiting and pagination."""

    def __init__(self, base_url: str, email: str, api_key: str):
        # Normalize URL: strip trailing slash, ensure /index.php?/api/v2 prefix
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/index.php"):
            self.base_url += "/index.php"
        self.api_prefix = self.base_url + "?/api/v2/"
        self.email = email
        self.api_key = api_key
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                auth=(self.email, self.api_key),
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Connection ──────────────────────────────────────────────

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection by fetching the current user. Returns user info dict."""
        return await self._request("GET", "get_current_user")

    # ── Projects & Suites ───────────────────────────────────────

    async def get_projects(self) -> list[dict[str, Any]]:
        """List all TestRail projects."""
        return await self._paginated_get("get_projects")

    async def get_suites(self, project_id: int) -> list[dict[str, Any]]:
        """List suites for a project."""
        data = await self._request("GET", f"get_suites/{project_id}")
        # Handle both list and paginated-wrapper responses
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list):
                    return val
        return []

    # ── Templates ────────────────────────────────────────────────

    async def get_templates(self, project_id: int) -> list[dict[str, Any]]:
        """List case templates for a project."""
        data = await self._request("GET", f"get_templates/{project_id}")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list):
                    return val
        return []

    # ── Sections ────────────────────────────────────────────────

    async def get_sections(self, project_id: int, suite_id: int) -> list[dict[str, Any]]:
        """List all sections in a suite."""
        return await self._paginated_get(f"get_sections/{project_id}", params={"suite_id": suite_id})

    async def add_section(
        self,
        project_id: int,
        suite_id: int,
        name: str,
        parent_id: int | None = None,
    ) -> dict[str, Any]:
        """Create a new section. Returns the created section."""
        payload: dict[str, Any] = {"suite_id": suite_id, "name": name}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        return await self._request("POST", f"add_section/{project_id}", json=payload)

    # ── Cases ───────────────────────────────────────────────────

    async def get_cases(
        self,
        project_id: int,
        suite_id: int,
        section_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List cases in a suite, optionally filtered by section."""
        params: dict[str, Any] = {"suite_id": suite_id}
        if section_id is not None:
            params["section_id"] = section_id
        return await self._paginated_get(f"get_cases/{project_id}", params=params)

    async def add_case(
        self,
        section_id: int,
        title: str,
        custom_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a test case in a section."""
        payload: dict[str, Any] = {"title": title}
        if custom_fields:
            payload.update(custom_fields)
        return await self._request("POST", f"add_case/{section_id}", json=payload)

    async def update_case(self, case_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an existing test case."""
        return await self._request("POST", f"update_case/{case_id}", json=updates)

    # ── Runs ──────────────────────────────────────────────────

    async def add_run(
        self,
        project_id: int,
        suite_id: int,
        name: str,
        description: str = "",
        case_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create a test run in a project. Returns the created run."""
        payload: dict[str, Any] = {
            "suite_id": suite_id,
            "name": name,
            "description": description,
            "include_all": False,
        }
        if case_ids:
            payload["case_ids"] = case_ids
        return await self._request("POST", f"add_run/{project_id}", json=payload)

    async def add_results_for_cases(self, run_id: int, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Bulk-add results for test cases in a run. Returns created results."""
        data = await self._request(
            "POST",
            f"add_results_for_cases/{run_id}",
            json={"results": results},
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list):
                    return val
        return []

    async def close_run(self, run_id: int) -> dict[str, Any]:
        """Close a test run (no more results can be added)."""
        return await self._request("POST", f"close_run/{run_id}")

    # ── Internal ────────────────────────────────────────────────

    @circuit(failure_threshold=5, recovery_timeout=60, expected_exception=Exception)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single API request with rate limiting and retry."""
        # Build URL manually: TestRail uses ?/api/v2/... format, so httpx's
        # params= would URL-encode the existing query and break the URL.
        url = self.api_prefix + endpoint
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = url + "&" + query
        max_retries = 3

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    client = self._get_client()
                    resp = await client.request(
                        method,
                        url,
                        json=json,
                    )

                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                        logger.warning("TestRail rate limit hit, retrying in %ds", retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status_code >= 400:
                        body = resp.text
                        raise TestrailError(
                            f"TestRail API {resp.status_code}: {body}",
                            status_code=resp.status_code,
                        )

                    data = resp.json()
                    return data

                except httpx.TimeoutException:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise TestrailError("TestRail API request timed out")
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise TestrailError(f"TestRail connection error: {e}")

        raise TestrailError("Max retries exceeded")

    async def _paginated_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Handle paginated GET requests. TestRail v2 uses offset/limit pagination."""
        all_items: list[dict[str, Any]] = []
        offset = 0
        limit = 250

        while True:
            p = dict(params or {})
            p["limit"] = limit
            p["offset"] = offset

            data = await self._request("GET", endpoint, params=p)

            # TestRail wraps paginated results: {"offset":0,"limit":250,"size":N,"_links":...,"XXX":[...]}
            if isinstance(data, dict):
                # Find the list key (varies: "projects", "sections", "cases", etc.)
                items = None
                for _key, val in data.items():
                    if isinstance(val, list):
                        items = val
                        break
                if items is None:
                    # Non-paginated response or empty
                    break
                all_items.extend(items)

                size = data.get("size", len(items))
                if size < limit:
                    break
                offset += limit
            elif isinstance(data, list):
                # Older API or non-paginated endpoint
                all_items.extend(data)
                break
            else:
                break

        return all_items

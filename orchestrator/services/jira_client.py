"""
Jira REST API Client - Async HTTP client for Jira REST API v2.

Supports both Jira Cloud and Jira Server/Data Center.
Uses httpx.AsyncClient with rate limiting and retry logic.
Mirrors the pattern from testrail_client.py.
"""

import asyncio
import base64
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


class JiraError(Exception):
    """Base exception for Jira API errors."""

    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


class JiraClient:
    """Async Jira REST API v2 client with rate limiting and retry."""

    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.api_prefix = self.base_url + "/rest/api/2/"
        self.email = email
        self.api_token = api_token
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
        self._client: httpx.AsyncClient | None = None
        # Basic auth: base64(email:token) for both Cloud and Server
        self._auth_header = "Basic " + base64.b64encode(f"{email}:{api_token}".encode()).decode()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": self._auth_header,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    def _get_upload_client(self) -> httpx.AsyncClient:
        """Separate client for multipart attachment uploads."""
        return httpx.AsyncClient(
            headers={
                "Authorization": self._auth_header,
                "X-Atlassian-Token": "no-check",
            },
            timeout=60.0,
        )

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Connection ──────────────────────────────────────────────

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection by fetching the current user. Returns user info dict."""
        return await self._request("GET", "myself")

    # ── Projects ────────────────────────────────────────────────

    async def get_projects(self) -> list[dict[str, Any]]:
        """List all accessible Jira projects."""
        data = await self._request("GET", "project")
        if isinstance(data, list):
            return data
        return []

    # ── Issue Types ─────────────────────────────────────────────

    async def get_issue_types(self, project_key: str) -> list[dict[str, Any]]:
        """Get available issue types for a project via createmeta."""
        # Try v2 createmeta first (works on Server and older Cloud)
        try:
            data = await self._request(
                "GET",
                "issue/createmeta",
                params={"projectKeys": project_key, "expand": "projects.issuetypes"},
            )
            if isinstance(data, dict):
                projects = data.get("projects", [])
                if projects:
                    return projects[0].get("issuetypes", [])
        except JiraError:
            pass

        # Fallback: use project endpoint
        try:
            data = await self._request("GET", f"project/{project_key}")
            if isinstance(data, dict):
                return data.get("issueTypes", [])
        except JiraError:
            pass

        return []

    # ── Issues ──────────────────────────────────────────────────

    async def create_issue(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Create a new Jira issue. Returns the created issue with key and id."""
        payload = {"fields": fields}
        return await self._request("POST", "issue", json=payload)

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Get issue details by key."""
        return await self._request("GET", f"issue/{issue_key}")

    # ── Attachments ─────────────────────────────────────────────

    @circuit(failure_threshold=5, recovery_timeout=60, expected_exception=Exception)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        reraise=True,
    )
    async def add_attachment(self, issue_key: str, filename: str, data: bytes) -> list[dict[str, Any]]:
        """Attach a file to an issue. Returns list of attachment metadata."""
        url = self.api_prefix + f"issue/{issue_key}/attachments"

        async with self._semaphore:
            upload_client = self._get_upload_client()
            try:
                resp = await upload_client.post(
                    url,
                    files={"file": (filename, data, "application/octet-stream")},
                )
                if resp.status_code >= 400:
                    raise JiraError(
                        f"Attachment upload failed {resp.status_code}: {resp.text}",
                        status_code=resp.status_code,
                    )
                result = resp.json()
                return result if isinstance(result, list) else [result]
            finally:
                await upload_client.aclose()

    # ── Priorities ──────────────────────────────────────────────

    async def get_priorities(self) -> list[dict[str, Any]]:
        """List available issue priorities."""
        data = await self._request("GET", "priority")
        if isinstance(data, list):
            return data
        return []

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
        url = self.api_prefix + endpoint
        max_retries = 3

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    client = self._get_client()
                    resp = await client.request(method, url, json=json, params=params)

                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                        logger.warning("Jira rate limit hit, retrying in %ds", retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status_code == 204:
                        return {}

                    if resp.status_code >= 400:
                        body = resp.text
                        raise JiraError(
                            f"Jira API {resp.status_code}: {body}",
                            status_code=resp.status_code,
                        )

                    return resp.json()

                except httpx.TimeoutException:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise JiraError("Jira API request timed out")
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise JiraError(f"Jira connection error: {e}")

        raise JiraError("Max retries exceeded")

"""
Jira REST API Client - Async HTTP client for Jira REST API v2.

Supports both Jira Cloud and Jira Server/Data Center.
Uses httpx.AsyncClient with rate limiting and retry logic.
Mirrors the pattern from testrail_client.py.
"""

import asyncio
import base64
import logging
import re
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


class JiraTransientError(JiraError):
    """Jira error that can reasonably be retried or circuit-broken."""


JIRA_AUTH_CLOUD_BASIC = "cloud_basic"
JIRA_AUTH_DATA_CENTER_PAT = "data_center_pat"
JIRA_AUTH_MODES = {JIRA_AUTH_CLOUD_BASIC, JIRA_AUTH_DATA_CENTER_PAT}


def summarize_jira_response(status_code: int, body: str, content_type: str = "") -> str:
    """Return a short, UI-safe summary of Jira error responses."""
    normalized_content_type = content_type.lower()
    if "html" in normalized_content_type or "<html" in body.lower():
        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
        ref_match = re.search(r"Error reference:\s*([^<\s]+)", body, flags=re.IGNORECASE)
        title = " ".join(title_match.group(1).split()) if title_match else "HTML error page"
        message = f"Jira API {status_code}: {title}"
        if ref_match:
            message += f" (error reference: {ref_match.group(1)})"
        return message

    compact_body = " ".join(body.split())
    if len(compact_body) > 500:
        compact_body = compact_body[:497] + "..."
    return f"Jira API {status_code}: {compact_body}"


class JiraClient:
    """Async Jira REST API v2 client with rate limiting and retry."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        auth_mode: str = JIRA_AUTH_CLOUD_BASIC,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_prefix = self.base_url + "/rest/api/2/"
        self.email = email
        self.api_token = api_token
        self.auth_mode = auth_mode if auth_mode in JIRA_AUTH_MODES else JIRA_AUTH_CLOUD_BASIC
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
        self._client: httpx.AsyncClient | None = None
        self._auth_header = self._build_auth_header()
        self.used_bearer_fallback = self.auth_mode == JIRA_AUTH_DATA_CENTER_PAT

    def _build_auth_header(self) -> str:
        if self.auth_mode == JIRA_AUTH_DATA_CENTER_PAT:
            return f"Bearer {self.api_token}"
        return "Basic " + base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()

    def _bearer_auth_header(self) -> str:
        return f"Bearer {self.api_token}"

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

    @circuit(failure_threshold=5, recovery_timeout=60, expected_exception=JiraTransientError)
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(JiraTransientError),
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

                    should_try_bearer = (
                        self.auth_mode == JIRA_AUTH_CLOUD_BASIC
                        and resp.status_code in {401, 403, 500}
                        and (
                            resp.status_code != 500
                            or "html" in resp.headers.get("Content-Type", "").lower()
                            or "<html" in resp.text[:500].lower()
                        )
                    )
                    if should_try_bearer:
                        bearer_resp = await client.request(
                            method,
                            url,
                            json=json,
                            params=params,
                            headers={"Authorization": self._bearer_auth_header()},
                        )
                        if bearer_resp.status_code < 400:
                            self.auth_mode = JIRA_AUTH_DATA_CENTER_PAT
                            self._auth_header = self._bearer_auth_header()
                            self.used_bearer_fallback = True
                            if self._client and not self._client.is_closed:
                                await self._client.aclose()
                                self._client = None
                            return {} if bearer_resp.status_code == 204 else bearer_resp.json()
                        resp = bearer_resp

                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                        logger.warning("Jira rate limit hit, retrying in %ds", retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status_code == 204:
                        return {}

                    if resp.status_code >= 400:
                        body = summarize_jira_response(
                            resp.status_code,
                            resp.text,
                            resp.headers.get("Content-Type", ""),
                        )
                        if resp.status_code >= 500 or resp.status_code == 429:
                            raise JiraTransientError(body, status_code=resp.status_code)
                        raise JiraError(body, status_code=resp.status_code)

                    return resp.json()

                except httpx.TimeoutException:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise JiraTransientError("Jira API request timed out")
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise JiraTransientError(f"Jira connection error: {e}")

        raise JiraTransientError("Max retries exceeded")

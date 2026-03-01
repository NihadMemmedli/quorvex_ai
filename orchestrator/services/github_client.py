"""
GitHub REST API Client - Async HTTP client for GitHub REST API.

Uses httpx.AsyncClient with rate limiting and retry logic.
Mirrors the pattern from gitlab_client.py and jira_client.py.
"""

import asyncio
import hashlib
import hmac
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GithubError(Exception):
    """Base exception for GitHub API errors."""

    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


class GithubClient:
    """Async GitHub REST API client with rate limiting and retry."""

    API_BASE = "https://api.github.com/"

    def __init__(self, token: str):
        self.token = token
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # -- Connection ------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection by fetching the authenticated user."""
        return await self._request("GET", "user")

    # -- Repositories ----------------------------------------------

    async def list_repos(self, search: str | None = None) -> list[dict[str, Any]]:
        """List repositories for the authenticated user, optionally filtered by search."""
        if search:
            data = await self._request(
                "GET",
                "search/repositories",
                params={"q": f"{search} in:name", "per_page": 50, "sort": "updated"},
            )
            if isinstance(data, dict):
                return data.get("items", [])
            return []

        data = await self._request("GET", "user/repos", params={"per_page": 50, "sort": "updated"})
        if isinstance(data, list):
            return data
        return []

    # -- Workflows -------------------------------------------------

    async def list_workflows(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """List GitHub Actions workflows for a repository."""
        data = await self._request("GET", f"repos/{owner}/{repo}/actions/workflows")
        if isinstance(data, dict):
            return data.get("workflows", [])
        return []

    async def trigger_workflow(
        self,
        owner: str,
        repo: str,
        workflow_id: str,
        ref: str,
        inputs: dict[str, str] | None = None,
    ) -> bool:
        """Trigger a workflow_dispatch event. Returns True on success (204)."""
        payload: dict[str, Any] = {"ref": ref, "inputs": inputs or {}}
        await self._request(
            "POST",
            f"repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
            json=payload,
        )
        return True

    # -- Workflow Runs ---------------------------------------------

    async def get_workflow_runs(
        self,
        owner: str,
        repo: str,
        workflow_id: str | None = None,
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        """List workflow runs for a repository, optionally filtered by workflow."""
        if workflow_id:
            path = f"repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
        else:
            path = f"repos/{owner}/{repo}/actions/runs"

        data = await self._request("GET", path, params={"per_page": per_page})
        if isinstance(data, dict):
            return data.get("workflow_runs", [])
        return []

    async def get_run(self, owner: str, repo: str, run_id: int) -> dict[str, Any]:
        """Get details of a specific workflow run."""
        return await self._request("GET", f"repos/{owner}/{repo}/actions/runs/{run_id}")

    async def get_run_jobs(self, owner: str, repo: str, run_id: int) -> list[dict[str, Any]]:
        """Get jobs for a specific workflow run."""
        data = await self._request("GET", f"repos/{owner}/{repo}/actions/runs/{run_id}/jobs")
        if isinstance(data, dict):
            return data.get("jobs", [])
        return []

    # -- Internal --------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single API request with rate limiting and retry.

        Retries up to 3 times with exponential backoff (1s, 2s, 4s)
        for 429 (rate limit) and 5xx (server error) responses.
        """
        url = self.API_BASE + endpoint
        max_retries = 3

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    client = self._get_client()
                    resp = await client.request(method, url, json=json, params=params)

                    # Retry on rate limit
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2**attempt))
                        logger.warning("GitHub rate limit hit, retrying in %ds", retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    # Retry on server errors
                    if resp.status_code >= 500:
                        if attempt < max_retries - 1:
                            wait = 2**attempt
                            logger.warning(
                                "GitHub server error %d, retrying in %ds",
                                resp.status_code,
                                wait,
                            )
                            await asyncio.sleep(wait)
                            continue

                    if resp.status_code == 204:
                        return {}

                    if resp.status_code >= 400:
                        body = resp.text
                        raise GithubError(
                            f"GitHub API {resp.status_code}: {body}",
                            status_code=resp.status_code,
                        )

                    return resp.json()

                except httpx.TimeoutException:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise GithubError("GitHub API request timed out")
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise GithubError(f"GitHub connection error: {e}")

        raise GithubError("Max retries exceeded")


def verify_webhook_signature(payload_body: bytes, signature_header: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)

"""
GitLab REST API Client - Async HTTP client for GitLab REST API v4.

Uses httpx.AsyncClient with rate limiting and retry logic.
Mirrors the pattern from jira_client.py.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GitlabError(Exception):
    """Base exception for GitLab API errors."""

    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


class GitlabClient:
    """Async GitLab REST API v4 client with rate limiting and retry."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.api_prefix = self.base_url + "/api/v4/"
        self.token = token
        self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "PRIVATE-TOKEN": self.token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # -- Connection ------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection by fetching the current user. Returns user info dict."""
        return await self._request("GET", "user")

    # -- Projects --------------------------------------------------

    async def list_projects(self, search: str | None = None) -> list[dict[str, Any]]:
        """List GitLab projects the authenticated user is a member of."""
        params: dict[str, Any] = {"membership": "true", "per_page": 50}
        if search:
            params["search"] = search
        data = await self._request("GET", "projects", params=params)
        if isinstance(data, list):
            return data
        return []

    async def get_project(self, project_id: int) -> dict[str, Any]:
        """Get a single GitLab project by ID."""
        return await self._request("GET", f"projects/{project_id}")

    # -- Pipelines -------------------------------------------------

    async def trigger_pipeline(
        self,
        project_id: int,
        ref: str,
        variables: dict[str, str] | None = None,
        trigger_token: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a new pipeline for a project.

        Uses the pipeline trigger token endpoint if trigger_token is provided,
        otherwise uses the standard create pipeline endpoint.
        """
        if trigger_token:
            # Use trigger token endpoint (works without project-level permissions)
            form_data: dict[str, Any] = {"token": trigger_token, "ref": ref}
            if variables:
                for key, value in variables.items():
                    form_data[f"variables[{key}]"] = value
            return await self._request(
                "POST",
                f"projects/{project_id}/trigger/pipeline",
                data=form_data,
            )
        else:
            # Use standard pipeline creation (requires developer+ access)
            payload: dict[str, Any] = {"ref": ref}
            if variables:
                payload["variables"] = [
                    {"key": k, "variable_type": "env_var", "value": v} for k, v in variables.items()
                ]
            return await self._request("POST", f"projects/{project_id}/pipeline", json=payload)

    async def get_pipeline(self, project_id: int, pipeline_id: int) -> dict[str, Any]:
        """Get details of a specific pipeline."""
        return await self._request("GET", f"projects/{project_id}/pipelines/{pipeline_id}")

    async def get_pipeline_jobs(self, project_id: int, pipeline_id: int) -> list[dict[str, Any]]:
        """Get jobs for a specific pipeline."""
        data = await self._request("GET", f"projects/{project_id}/pipelines/{pipeline_id}/jobs")
        if isinstance(data, list):
            return data
        return []

    async def get_pipeline_test_report(self, project_id: int, pipeline_id: int) -> dict[str, Any]:
        """Get the test report for a specific pipeline."""
        return await self._request("GET", f"projects/{project_id}/pipelines/{pipeline_id}/test_report")

    # -- Internal --------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single API request with rate limiting and retry.

        Retries up to 3 times with exponential backoff (1s, 2s, 4s)
        for 429 (rate limit) and 5xx (server error) responses.
        """
        url = self.api_prefix + endpoint
        max_retries = 3

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    client = self._get_client()

                    # For form-encoded data (trigger endpoint), use different content type
                    if data is not None:
                        resp = await client.request(
                            method,
                            url,
                            data=data,
                            params=params,
                            headers={
                                "PRIVATE-TOKEN": self.token,
                                "Accept": "application/json",
                            },
                        )
                    else:
                        resp = await client.request(method, url, json=json, params=params)

                    # Retry on rate limit
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("Retry-After", 2**attempt))
                        logger.warning("GitLab rate limit hit, retrying in %ds", retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    # Retry on server errors
                    if resp.status_code >= 500:
                        if attempt < max_retries - 1:
                            wait = 2**attempt
                            logger.warning(
                                "GitLab server error %d, retrying in %ds",
                                resp.status_code,
                                wait,
                            )
                            await asyncio.sleep(wait)
                            continue

                    if resp.status_code == 204:
                        return {}

                    if resp.status_code >= 400:
                        body = resp.text
                        raise GitlabError(
                            f"GitLab API {resp.status_code}: {body}",
                            status_code=resp.status_code,
                        )

                    return resp.json()

                except httpx.TimeoutException:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise GitlabError("GitLab API request timed out")
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise GitlabError(f"GitLab connection error: {e}")

        raise GitlabError("Max retries exceeded")

"""
GitHub REST API Client - Async HTTP client for GitHub REST API.

Uses httpx.AsyncClient with rate limiting and retry logic.
Mirrors the pattern from gitlab_client.py and jira_client.py.
"""

import asyncio
import base64
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

    async def get_repository(self, owner: str, repo: str) -> dict[str, Any]:
        """Fetch repository metadata."""
        return await self._request("GET", f"repos/{owner}/{repo}")

    async def get_tree(self, owner: str, repo: str, ref: str, recursive: bool = True) -> list[dict[str, Any]]:
        """Fetch a Git tree for a branch, tag, or commit SHA."""
        params = {"recursive": "1"} if recursive else None
        data = await self._request("GET", f"repos/{owner}/{repo}/git/trees/{ref}", params=params)
        if isinstance(data, dict):
            return data.get("tree", [])
        return []

    async def get_file_content(self, owner: str, repo: str, path: str, ref: str | None = None) -> str | None:
        """Fetch and decode a text file from a repository."""
        params = {"ref": ref} if ref else None
        data = await self._request("GET", f"repos/{owner}/{repo}/contents/{path}", params=params)
        if not isinstance(data, dict):
            return None
        content = data.get("content")
        encoding = data.get("encoding")
        if not content or encoding != "base64":
            return None
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None

    async def get_ref(self, owner: str, repo: str, ref: str) -> dict[str, Any]:
        """Fetch a Git ref such as heads/main."""
        clean_ref = ref.removeprefix("refs/")
        return await self._request("GET", f"repos/{owner}/{repo}/git/ref/{clean_ref}")

    async def create_ref(self, owner: str, repo: str, ref: str, sha: str) -> dict[str, Any]:
        """Create a Git ref from an existing commit SHA."""
        full_ref = ref if ref.startswith("refs/") else f"refs/{ref}"
        return await self._request(
            "POST",
            f"repos/{owner}/{repo}/git/refs",
            json={"ref": full_ref, "sha": sha},
        )

    async def get_content_metadata(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch repository content metadata, including SHA, without discarding GitHub fields."""
        params = {"ref": ref} if ref else None
        try:
            data = await self._request("GET", f"repos/{owner}/{repo}/contents/{path}", params=params)
        except GithubError as exc:
            if exc.status_code == 404:
                return None
            raise
        return data if isinstance(data, dict) else None

    async def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        content: str,
        message: str,
        branch: str,
        sha: str | None = None,
    ) -> dict[str, Any]:
        """Create or update a text file on a branch using the Contents API."""
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        return await self._request(
            "PUT",
            f"repos/{owner}/{repo}/contents/{path}",
            json=payload,
        )

    # -- Pull Requests ---------------------------------------------

    async def get_pull_request(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """Fetch metadata for a pull request."""
        return await self._request("GET", f"repos/{owner}/{repo}/pulls/{pr_number}")

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        head: str,
        base: str,
        body: str,
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a pull request."""
        return await self._request(
            "POST",
            f"repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        head: str | None = None,
        base: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """List pull requests, optionally filtered by head/base."""
        safe_limit = max(1, min(int(limit or 30), 100))
        pulls: list[dict[str, Any]] = []
        page = 1
        while len(pulls) < safe_limit:
            params: dict[str, Any] = {"state": state, "per_page": min(100, safe_limit - len(pulls)), "page": page}
            if head:
                params["head"] = head
            if base:
                params["base"] = base
            data = await self._request("GET", f"repos/{owner}/{repo}/pulls", params=params)
            if not isinstance(data, list) or not data:
                break
            pulls.extend(data)
            if len(data) < params["per_page"]:
                break
            page += 1
        return pulls[:safe_limit]

    async def list_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """List files changed by a pull request, following GitHub pagination."""
        files: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        while True:
            data = await self._request(
                "GET",
                f"repos/{owner}/{repo}/pulls/{pr_number}/files",
                params={"per_page": per_page, "page": page},
            )
            if not isinstance(data, list) or not data:
                break
            files.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return files

    async def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict[str, Any]]:
        """List comments on an issue or pull request."""
        data = await self._request(
            "GET",
            f"repos/{owner}/{repo}/issues/{issue_number}/comments",
            params={"per_page": 100},
        )
        if isinstance(data, list):
            return data
        return []

    async def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        """Create a comment on an issue or pull request."""
        return await self._request(
            "POST",
            f"repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    async def update_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict[str, Any]:
        """Update an existing issue or pull request comment."""
        return await self._request(
            "PATCH",
            f"repos/{owner}/{repo}/issues/comments/{comment_id}",
            json={"body": body},
        )

    async def create_commit_status(
        self,
        owner: str,
        repo: str,
        sha: str,
        *,
        state: str,
        context: str,
        description: str,
        target_url: str | None = None,
    ) -> dict[str, Any]:
        """Create a GitHub commit status for a SHA."""
        payload: dict[str, Any] = {
            "state": state,
            "context": context,
            "description": description[:140],
        }
        if target_url:
            payload["target_url"] = target_url
        return await self._request(
            "POST",
            f"repos/{owner}/{repo}/statuses/{sha}",
            json=payload,
        )

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

    async def cancel_run(self, owner: str, repo: str, run_id: int) -> bool:
        """Cancel a workflow run."""
        await self._request("POST", f"repos/{owner}/{repo}/actions/runs/{run_id}/cancel")
        return True

    async def rerun_run(self, owner: str, repo: str, run_id: int, failed_only: bool = False) -> bool:
        """Rerun a workflow run, optionally only failed jobs."""
        endpoint = "rerun-failed-jobs" if failed_only else "rerun"
        await self._request("POST", f"repos/{owner}/{repo}/actions/runs/{run_id}/{endpoint}")
        return True

    async def list_run_artifacts(self, owner: str, repo: str, run_id: int) -> list[dict[str, Any]]:
        """List artifacts produced by a workflow run."""
        data = await self._request("GET", f"repos/{owner}/{repo}/actions/runs/{run_id}/artifacts")
        if isinstance(data, dict):
            return data.get("artifacts", [])
        return []

    async def get_run_logs_url(self, owner: str, repo: str, run_id: int) -> str | None:
        """Return the short-lived redirected download URL for a workflow run log archive."""
        resp = await self._raw_request("GET", f"repos/{owner}/{repo}/actions/runs/{run_id}/logs")
        if 300 <= resp.status_code < 400:
            return resp.headers.get("location")
        if resp.status_code == 200:
            return str(resp.url)
        return None

    # -- Internal --------------------------------------------------

    async def _raw_request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Execute an API request and return the raw response."""
        url = self.API_BASE + endpoint
        async with self._semaphore:
            client = self._get_client()
            resp = await client.request(method, url, json=json, params=params, follow_redirects=False)
            if resp.status_code >= 400:
                raise GithubError(f"GitHub API {resp.status_code}: {resp.text}", status_code=resp.status_code)
            return resp

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

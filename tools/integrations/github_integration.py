"""GitHub API integration for repository management, PR, issues, actions.

Implements :class:`BaseIntegration` against GitHub REST API v3.

Configuration keys:
- token (str, optional): GitHub Personal Access Token or OAuth token
- owner (str, optional): Default repository owner
- repo (str, optional): Default repository name
- api_base (str, optional): Defaults to "https://api.github.com"
"""

from __future__ import annotations

import asyncio
import binascii
import logging
import os
from typing import Any

import httpx

from tools.integrations.base import (
    AuthError,
    BaseIntegration,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ReceiveCallback,
    safe_call,
    sleep_for,
)
from tools.integrations.registry import register_integration

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3


@register_integration("github")
class GitHubIntegration(BaseIntegration):
    """GitHub REST API v3 client."""

    platform_name = "github"
    BASE_URL = DEFAULT_API_BASE

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.token: str = config.get("token", "") or os.environ.get("GITHUB_TOKEN", "")
        self.default_owner: str = config.get("owner", "")
        self.default_repo: str = config.get("repo", "")
        self.api_base: str = config.get("api_base", DEFAULT_API_BASE)
        self.timeout: float = float(config.get("timeout", DEFAULT_TIMEOUT))
        self.headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ZelooGitHubIntegration/1.0",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        self._client: httpx.AsyncClient | None = None
        self._event_callback: ReceiveCallback | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=self.timeout,
                headers=self.headers,
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()
        attempts = MAX_RETRIES + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "GitHub HTTP error on %s (attempt %s/%s): %s",
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 1.0))
                logger.info("GitHub rate-limited, sleeping %.2fs", retry_after)
                await sleep_for(retry_after)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"GitHub rate limit exceeded for {path}",
                    retry_after=retry_after,
                )

            if response.status_code == 401:
                raise AuthError(f"GitHub auth failure: {response.text}")
            if response.status_code == 403:
                if "rate limit" in response.text.lower():
                    raise RateLimitError("GitHub rate limit exceeded")
                raise AuthError(f"GitHub forbidden: {response.text}")
            if response.status_code == 404:
                raise NotFoundError(f"GitHub resource missing: {path}")
            if 500 <= response.status_code < 600:
                last_error = IntegrationError(
                    f"GitHub server error {response.status_code}"
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            try:
                payload = response.json()
            except Exception as exc:
                raise IntegrationError(f"Invalid GitHub response: {exc}") from exc

            return payload

        assert last_error is not None
        raise IntegrationError(
            f"GitHub request failed after retries: {last_error}"
        )

    def _resolve_owner_repo(
        self,
        owner: str = "",
        repo: str = "",
    ) -> tuple[str, str]:
        return (owner or self.default_owner, repo or self.default_repo)

    def _encode_content(self, content: str) -> str:
        import base64
        return base64.b64encode(content.encode("utf-8")).decode("ascii")

    def _decode_content(self, content: str) -> str:
        import base64
        return base64.b64decode(content.encode("ascii")).decode("utf-8")

    async def send_message(
        self,
        channel: str,
        content: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create an issue comment or update existing issue.

        Args:
            channel: Issue number or "new" for new issue
            content: Comment or issue body
        """
        if channel == "new":
            return await self.create_issue(
                title=kwargs.get("title", "New Issue"),
                body=content,
                owner=kwargs.get("owner", ""),
                repo=kwargs.get("repo", ""),
            )
        return await self.add_comment(
            body=content,
            issue_number=int(channel),
            owner=kwargs.get("owner", ""),
            repo=kwargs.get("repo", ""),
        )

    async def get_file(
        self,
        path: str,
        owner: str = "",
        repo: str = "",
        ref: str = "main",
    ) -> dict[str, Any]:
        """Get file content from repository."""

        async def _do() -> dict[str, Any]:
            o, r = self._resolve_owner_repo(owner, repo)
            result = await self._request(
                "GET",
                f"/repos/{o}/{r}/contents/{path}",
                params={"ref": ref},
            )
            content = result.get("content", "")
            decoded = self._decode_content(content.replace("\n", "")) if content else ""
            return {
                "ok": True,
                "path": result.get("path"),
                "sha": result.get("sha"),
                "content": decoded,
                "size": result.get("size"),
                "encoding": result.get("encoding"),
                "raw": result,
            }

        return await safe_call(_do)

    async def create_file(
        self,
        path: str,
        content: str,
        message: str,
        owner: str = "",
        repo: str = "",
        branch: str = "",
    ) -> dict[str, Any]:
        """Create a new file in repository."""

        async def _do() -> dict[str, Any]:
            o, r = self._resolve_owner_repo(owner, repo)
            payload: dict[str, Any] = {
                "message": message,
                "content": self._encode_content(content),
            }
            if branch:
                payload["branch"] = branch
            result = await self._request(
                "PUT",
                f"/repos/{o}/{r}/contents/{path}",
                json_body=payload,
            )
            return {
                "ok": True,
                "commit": result.get("commit", {}),
                "content": result.get("content", {}),
                "raw": result,
            }

        return await safe_call(_do)

    async def update_file(
        self,
        path: str,
        content: str,
        message: str,
        sha: str,
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Update an existing file in repository."""

        async def _do() -> dict[str, Any]:
            o, r = self._resolve_owner_repo(owner, repo)
            payload = {
                "message": message,
                "content": self._encode_content(content),
                "sha": sha,
            }
            result = await self._request(
                "PUT",
                f"/repos/{o}/{r}/contents/{path}",
                json_body=payload,
            )
            return {
                "ok": True,
                "commit": result.get("commit", {}),
                "content": result.get("content", {}),
                "raw": result,
            }

        return await safe_call(_do)

    async def list_pulls(
        self,
        state: str = "open",
        owner: str = "",
        repo: str = "",
    ) -> list[dict[str, Any]]:
        """List pull requests."""

        async def _do() -> list[dict[str, Any]]:
            o, r = self._resolve_owner_repo(owner, repo)
            result = await self._request(
                "GET",
                f"/repos/{o}/{r}/pulls",
                params={"state": state},
            )
            return result if isinstance(result, list) else []

        return await safe_call(_do)

    async def create_pull(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Create a pull request."""

        async def _do() -> dict[str, Any]:
            o, r = self._resolve_owner_repo(owner, repo)
            payload = {
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            }
            result = await self._request(
                "POST",
                f"/repos/{o}/{r}/pulls",
                json_body=payload,
            )
            return {
                "ok": True,
                "number": result.get("number"),
                "html_url": result.get("html_url"),
                "raw": result,
            }

        return await safe_call(_do)

    async def list_issues(
        self,
        state: str = "open",
        owner: str = "",
        repo: str = "",
    ) -> list[dict[str, Any]]:
        """List repository issues."""

        async def _do() -> list[dict[str, Any]]:
            o, r = self._resolve_owner_repo(owner, repo)
            result = await self._request(
                "GET",
                f"/repos/{o}/{r}/issues",
                params={"state": state},
            )
            return result if isinstance(result, list) else []

        return await safe_call(_do)

    async def create_issue(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Create a new issue."""

        async def _do() -> dict[str, Any]:
            o, r = self._resolve_owner_repo(owner, repo)
            payload: dict[str, Any] = {"title": title, "body": body}
            if labels:
                payload["labels"] = labels
            result = await self._request(
                "POST",
                f"/repos/{o}/{r}/issues",
                json_body=payload,
            )
            return {
                "ok": True,
                "number": result.get("number"),
                "html_url": result.get("html_url"),
                "raw": result,
            }

        return await safe_call(_do)

    async def add_comment(
        self,
        body: str,
        issue_number: int,
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Add a comment to an issue or pull request."""

        async def _do() -> dict[str, Any]:
            o, r = self._resolve_owner_repo(owner, repo)
            result = await self._request(
                "POST",
                f"/repos/{o}/{r}/issues/{issue_number}/comments",
                json_body={"body": body},
            )
            return {
                "ok": True,
                "id": result.get("id"),
                "html_url": result.get("html_url"),
                "raw": result,
            }

        return await safe_call(_do)

    async def list_workflows(
        self,
        owner: str = "",
        repo: str = "",
    ) -> list[dict[str, Any]]:
        """List repository workflows."""

        async def _do() -> list[dict[str, Any]]:
            o, r = self._resolve_owner_repo(owner, repo)
            result = await self._request(
                "GET",
                f"/repos/{o}/{r}/actions/workflows",
            )
            workflows = result.get("workflows", [])
            return workflows if isinstance(workflows, list) else []

        return await safe_call(_do)

    async def trigger_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, Any] | None = None,
        ref: str = "main",
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Trigger a workflow dispatch."""

        async def _do() -> dict[str, Any]:
            o, r = self._resolve_owner_repo(owner, repo)
            payload: dict[str, Any] = {"ref": ref}
            if inputs:
                payload["inputs"] = inputs
            result = await self._request(
                "POST",
                f"/repos/{o}/{r}/actions/workflows/{workflow_id}/dispatches",
                json_body=payload,
            )
            return {"ok": True, "status": "workflow_dispatched", "raw": result}

        return await safe_call(_do)

    async def get_workflow_runs(
        self,
        workflow_id: str,
        owner: str = "",
        repo: str = "",
    ) -> list[dict[str, Any]]:
        """Get workflow runs."""

        async def _do() -> list[dict[str, Any]]:
            o, r = self._resolve_owner_repo(owner, repo)
            result = await self._request(
                "GET",
                f"/repos/{o}/{r}/actions/workflows/{workflow_id}/runs",
            )
            runs = result.get("workflow_runs", [])
            return runs if isinstance(runs, list) else []

        return await safe_call(_do)

    async def list_channels(self) -> list[dict[str, Any]]:
        """List repository info as pseudo-channels."""
        o, r = self._resolve_owner_repo()
        if not o or not r:
            return []
        async def _do() -> list[dict[str, Any]]:
            result = await self._request("GET", f"/repos/{o}/{r}")
            return [{"name": result.get("full_name"), "url": result.get("html_url")}]
        return await safe_call(_do)

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get GitHub user information."""
        async def _do() -> dict[str, Any]:
            result = await self._request("GET", f"/users/{user_id}")
            return {
                "ok": True,
                "login": result.get("login"),
                "name": result.get("name"),
                "bio": result.get("bio"),
                "raw": result,
            }
        return await safe_call(_do)

    async def receive_messages(
        self,
        callback: ReceiveCallback,
        **kwargs: Any,
    ) -> None:
        """Store callback for webhook events."""
        self._event_callback = callback

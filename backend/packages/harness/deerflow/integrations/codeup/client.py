"""Codeup OpenAPI client.

Supports both central-edition (with organizationId) and Region-edition APIs.
Authentication uses x-yunxiao-token header with a Personal Access Token (PAT).
"""

import logging
from urllib.parse import quote

import httpx

from .models import ChangeRequest, Repository

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class CodeupConfigurationError(Exception):
    """Raised when Codeup client is misconfigured (e.g., missing token)."""


class CodeupAPIError(Exception):
    """Raised when a Codeup API call fails after retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CodeupClient:
    """Client for Alibaba Cloud Codeup OpenAPI.

    Usage::

        client = CodeupClient(token="pt-xxx", domain="devops.aliyun.com")
        repos = await client.list_repositories()
        mr = await client.create_change_request(
            repository_id=123,
            source_branch="feature/my-feature",
            target_branch="main",
            title="feat: my feature",
            description="...",
        )
    """

    def __init__(
        self,
        token: str,
        domain: str,
        organization_id: str | None = None,
    ) -> None:
        """Initialize the Codeup client.

        Args:
            token: Personal Access Token for x-yunxiao-token authentication.
            domain: Codeup API domain (without protocol prefix).
            organization_id: Organization ID required for central-edition; omit for Region edition.

        Raises:
            CodeupConfigurationError: If token or domain is not provided.
        """
        if not token:
            raise CodeupConfigurationError("Codeup token is required. Set the CODEUP_TOKEN environment variable and configure codeup.token in config.yaml.")
        if not domain:
            raise CodeupConfigurationError("Codeup domain is required. Set the CODEUP_DOMAIN environment variable and configure codeup.domain in config.yaml.")
        self._token = token
        self._domain = domain
        self._organization_id = organization_id
        self._base_url = f"https://{domain}"
        self._headers = {
            "x-yunxiao-token": token,
            "Content-Type": "application/json",
        }

    def _build_url(self, path: str) -> str:
        """Build a full API URL for central or Region edition."""
        if self._organization_id:
            return f"{self._base_url}/oapi/v1/codeup/organizations/{self._organization_id}{path}"
        return f"{self._base_url}/oapi/v1/codeup{path}"

    async def list_repositories(
        self,
        page: int = 1,
        per_page: int = 100,
        search: str | None = None,
        archived: bool = False,
    ) -> list[Repository]:
        """List accessible Codeup repositories.

        Args:
            page: Page number (1-based).
            per_page: Page size (1-100).
            search: Optional fuzzy search keyword.
            archived: Include archived repositories.

        Returns:
            List of Repository objects.

        Raises:
            CodeupAPIError: If the API call fails.
        """
        url = self._build_url("/repositories")
        params: dict = {"page": page, "perPage": per_page, "archived": str(archived).lower()}
        if search:
            params["search"] = search

        async with httpx.AsyncClient() as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    response = await client.get(url, headers=self._headers, params=params, timeout=30)
                    if response.status_code == 200:
                        return [Repository.model_validate(item) for item in response.json()]
                    raise CodeupAPIError(
                        f"list_repositories failed: HTTP {response.status_code} - {response.text}",
                        status_code=response.status_code,
                    )
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    if attempt == _MAX_RETRIES:
                        raise CodeupAPIError(f"list_repositories failed after {_MAX_RETRIES} retries: {e}") from e
                    logger.warning("list_repositories attempt %d/%d failed: %s", attempt, _MAX_RETRIES, e)

        return []

    async def get_repository(self, repository_id: int | str) -> Repository:
        """Get a specific repository by ID or URL-encoded full path.

        Args:
            repository_id: Repository integer ID or URL-encoded full path.

        Returns:
            Repository object.

        Raises:
            CodeupAPIError: If the API call fails or repository not found.
        """
        encoded_id = quote(str(repository_id), safe="") if isinstance(repository_id, str) else repository_id
        url = self._build_url(f"/repositories/{encoded_id}")

        async with httpx.AsyncClient() as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    response = await client.get(url, headers=self._headers, timeout=30)
                    if response.status_code == 200:
                        return Repository.model_validate(response.json())
                    raise CodeupAPIError(
                        f"get_repository failed: HTTP {response.status_code} - {response.text}",
                        status_code=response.status_code,
                    )
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    if attempt == _MAX_RETRIES:
                        raise CodeupAPIError(f"get_repository failed after {_MAX_RETRIES} retries: {e}") from e
                    logger.warning("get_repository attempt %d/%d failed: %s", attempt, _MAX_RETRIES, e)

        raise CodeupAPIError("get_repository failed: unreachable")

    async def create_change_request(
        self,
        repository_id: int | str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        reviewer_user_ids: list[str] | None = None,
        work_item_ids: str | None = None,
    ) -> ChangeRequest:
        """Create a Merge Request (Change Request) in Codeup.

        Args:
            repository_id: Repository integer ID or URL-encoded full path.
            source_branch: Source branch name (feature branch).
            target_branch: Target branch name (e.g., "main" or "master").
            title: MR title (max 256 chars).
            description: MR description (max 10000 chars).
            reviewer_user_ids: Optional list of reviewer Yunxiao user IDs.
            work_item_ids: Comma-separated work item IDs to associate.

        Returns:
            ChangeRequest object with MR details including web_url.

        Raises:
            CodeupAPIError: If the API call fails.
        """
        encoded_id = quote(str(repository_id), safe="") if isinstance(repository_id, str) else repository_id
        url = self._build_url(f"/repositories/{encoded_id}/changeRequests")

        body: dict = {
            "sourceBranch": source_branch,
            "targetBranch": target_branch,
            "sourceProjectId": repository_id if isinstance(repository_id, int) else 0,
            "targetProjectId": repository_id if isinstance(repository_id, int) else 0,
            "title": title[:256],
            "description": description[:10000],
            "createFrom": "COMMAND_LINE",
        }
        if reviewer_user_ids:
            body["reviewerUserIds"] = reviewer_user_ids
        if work_item_ids:
            body["workItemIds"] = work_item_ids

        async with httpx.AsyncClient() as client:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    response = await client.post(url, headers=self._headers, json=body, timeout=30)
                    if response.status_code in (200, 201):
                        return ChangeRequest.model_validate(response.json())
                    raise CodeupAPIError(
                        f"create_change_request failed: HTTP {response.status_code} - {response.text}",
                        status_code=response.status_code,
                    )
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    if attempt == _MAX_RETRIES:
                        raise CodeupAPIError(f"create_change_request failed after {_MAX_RETRIES} retries: {e}") from e
                    logger.warning("create_change_request attempt %d/%d failed: %s", attempt, _MAX_RETRIES, e)

        raise CodeupAPIError("create_change_request failed: unreachable")

    @classmethod
    def from_config(cls) -> "CodeupClient":
        """Create a CodeupClient from the application configuration.

        Returns:
            CodeupClient instance configured from config.yaml.

        Raises:
            CodeupConfigurationError: If required config values are missing.
        """
        from deerflow.config import get_app_config

        config = get_app_config()
        codeup_cfg = config.codeup
        return cls(
            token=codeup_cfg.token,
            domain=codeup_cfg.domain,
            organization_id=codeup_cfg.organization_id,
        )

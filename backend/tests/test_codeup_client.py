"""Unit tests for the Codeup API client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.integrations.codeup.client import CodeupAPIError, CodeupClient, CodeupConfigurationError
from deerflow.integrations.codeup.models import ChangeRequest, Repository

# ---------------------------------------------------------------------------
# CodeupClient construction
# ---------------------------------------------------------------------------


def test_client_raises_when_token_missing() -> None:
    with pytest.raises(CodeupConfigurationError, match="CODEUP_TOKEN"):
        CodeupClient(token="", domain="example.com")


def test_client_raises_when_domain_missing() -> None:
    with pytest.raises(CodeupConfigurationError, match="CODEUP_DOMAIN"):
        CodeupClient(token="pt-xxx", domain="")


def test_client_builds_region_url() -> None:
    client = CodeupClient(token="pt-xxx", domain="devops.aliyun.com")
    assert client._build_url("/repositories") == "https://devops.aliyun.com/oapi/v1/codeup/repositories"


def test_client_builds_central_url_with_org_id() -> None:
    client = CodeupClient(token="pt-xxx", domain="devops.aliyun.com", organization_id="org123")
    assert client._build_url("/repositories") == "https://devops.aliyun.com/oapi/v1/codeup/organizations/org123/repositories"


# ---------------------------------------------------------------------------
# list_repositories
# ---------------------------------------------------------------------------


def test_list_repositories_success() -> None:
    mock_data = [
        {
            "id": 1,
            "name": "demo-repo",
            "path": "demo-repo",
            "pathWithNamespace": "org/demo-repo",
            "description": "Demo",
            "visibility": "private",
            "webUrl": "https://example.com/org/demo-repo",
            "archived": False,
        }
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client = CodeupClient(token="pt-xxx", domain="devops.aliyun.com")
    with patch("httpx.AsyncClient") as mock_httpx:
        mock_httpx.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        repos = asyncio.run(client.list_repositories())

    assert len(repos) == 1
    assert isinstance(repos[0], Repository)
    assert repos[0].name == "demo-repo"
    assert repos[0].id == 1


def test_list_repositories_api_error() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    client = CodeupClient(token="bad-token", domain="devops.aliyun.com")
    with patch("httpx.AsyncClient") as mock_httpx:
        mock_httpx.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        with pytest.raises(CodeupAPIError, match="HTTP 401"):
            asyncio.run(client.list_repositories())


# ---------------------------------------------------------------------------
# get_repository
# ---------------------------------------------------------------------------


def test_get_repository_success() -> None:
    mock_data = {
        "id": 42,
        "name": "my-repo",
        "path": "my-repo",
        "pathWithNamespace": "org/my-repo",
        "description": None,
        "visibility": "internal",
        "webUrl": "https://example.com/org/my-repo",
        "archived": False,
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_data

    client = CodeupClient(token="pt-xxx", domain="devops.aliyun.com")
    with patch("httpx.AsyncClient") as mock_httpx:
        mock_httpx.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        repo = asyncio.run(client.get_repository(42))

    assert isinstance(repo, Repository)
    assert repo.id == 42
    assert repo.name == "my-repo"


# ---------------------------------------------------------------------------
# create_change_request
# ---------------------------------------------------------------------------


def test_create_change_request_success() -> None:
    mock_data = {
        "localId": 7,
        "title": "feat: awesome feature",
        "description": "Some description",
        "status": "UNDER_REVIEW",
        "sourceBranch": "feature/awesome",
        "targetBranch": "main",
        "webUrl": "https://example.com/org/repo/change/7",
        "detailUrl": "https://example.com/org/repo/change/7",
        "projectId": 42,
    }
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = mock_data

    client = CodeupClient(token="pt-xxx", domain="devops.aliyun.com")
    with patch("httpx.AsyncClient") as mock_httpx:
        mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        mr = asyncio.run(
            client.create_change_request(
                repository_id=42,
                source_branch="feature/awesome",
                target_branch="main",
                title="feat: awesome feature",
                description="Some description",
            )
        )

    assert isinstance(mr, ChangeRequest)
    assert mr.local_id == 7
    assert mr.web_url == "https://example.com/org/repo/change/7"


def test_create_change_request_server_error() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"

    client = CodeupClient(token="pt-xxx", domain="devops.aliyun.com")
    with patch("httpx.AsyncClient") as mock_httpx:
        mock_httpx.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        with pytest.raises(CodeupAPIError, match="HTTP 500"):
            asyncio.run(
                client.create_change_request(
                    repository_id=42,
                    source_branch="feature/foo",
                    target_branch="main",
                    title="Test MR",
                )
            )


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


def test_from_config_raises_when_not_configured() -> None:
    from deerflow.config.codeup_config import CodeupConfig

    mock_config = MagicMock()
    mock_config.codeup = CodeupConfig(token="", domain="")

    with patch("deerflow.config.app_config.get_app_config", return_value=mock_config):
        with patch("deerflow.config.get_app_config", return_value=mock_config):
            with pytest.raises(CodeupConfigurationError):
                CodeupClient.from_config()


def test_from_config_success() -> None:
    from deerflow.config.codeup_config import CodeupConfig

    mock_config = MagicMock()
    mock_config.codeup = CodeupConfig(token="pt-test", domain="devops.aliyun.com")

    with patch("deerflow.config.get_app_config", return_value=mock_config):
        client = CodeupClient.from_config()
        assert client._token == "pt-test"
        assert client._domain == "devops.aliyun.com"

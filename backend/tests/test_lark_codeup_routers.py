"""Integration tests for Lark and Codeup Gateway API routers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers.codeup import router as codeup_router
from app.gateway.routers.lark import router as lark_router


@pytest.fixture
def lark_app() -> FastAPI:
    app = FastAPI()
    app.include_router(lark_router)
    return app


@pytest.fixture
def codeup_app() -> FastAPI:
    app = FastAPI()
    app.include_router(codeup_router)
    return app


# ---------------------------------------------------------------------------
# Lark requirements router
# ---------------------------------------------------------------------------


def test_get_requirements_returns_200_with_empty_list(lark_app: FastAPI) -> None:
    with patch("app.gateway.routers.lark._fetch_requirements_via_mcp", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        client = TestClient(lark_app)
        response = client.get("/api/lark/requirements")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["requirements"] == []


def test_get_requirements_returns_requirement_list(lark_app: FastAPI) -> None:
    from app.gateway.routers.lark import LarkRequirement

    mock_reqs = [
        LarkRequirement(id="req-001", title="REQ-001", status="进行中", type="需求", assignee="张三"),
        LarkRequirement(id="bug-102", title="BUG-102", status="待排期", type="缺陷"),
    ]

    with patch("app.gateway.routers.lark._fetch_requirements_via_mcp", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_reqs
        client = TestClient(lark_app)
        response = client.get("/api/lark/requirements")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["requirements"][0]["id"] == "req-001"
    assert data["requirements"][0]["title"] == "REQ-001"


def test_get_requirements_returns_503_when_mcp_unavailable(lark_app: FastAPI) -> None:
    with patch("app.gateway.routers.lark._fetch_requirements_via_mcp", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = RuntimeError("FeishuProjectMcp SSE connection timeout")
        client = TestClient(lark_app, raise_server_exceptions=False)
        response = client.get("/api/lark/requirements")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["error"] == "feishu_mcp_unavailable"


def test_get_requirements_passes_iteration_filter(lark_app: FastAPI) -> None:
    with patch("app.gateway.routers.lark._fetch_requirements_via_mcp", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        client = TestClient(lark_app)
        client.get("/api/lark/requirements?iteration=sprint-5")

    mock_fetch.assert_called_once_with(iteration_id="sprint-5")


# ---------------------------------------------------------------------------
# Codeup repositories router
# ---------------------------------------------------------------------------


def test_list_repositories_returns_200(codeup_app: FastAPI) -> None:
    from deerflow.integrations.codeup.models import Repository

    mock_repos = [
        Repository(
            id=1,
            name="deer-flow-backend",
            path="deer-flow-backend",
            pathWithNamespace="org/deer-flow-backend",
            visibility="private",
            webUrl="https://example.com/org/deer-flow-backend",
            archived=False,
        )
    ]

    mock_client = MagicMock()
    mock_client.list_repositories = AsyncMock(return_value=mock_repos)

    with patch("app.gateway.routers.codeup.CodeupClient.from_config", return_value=mock_client):
        client = TestClient(codeup_app)
        response = client.get("/api/codeup/repositories")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["repositories"][0]["name"] == "deer-flow-backend"


def test_list_repositories_returns_503_when_not_configured(codeup_app: FastAPI) -> None:
    from deerflow.integrations.codeup.client import CodeupConfigurationError

    with patch("app.gateway.routers.codeup.CodeupClient.from_config", side_effect=CodeupConfigurationError("CODEUP_TOKEN not set")):
        client = TestClient(codeup_app, raise_server_exceptions=False)
        response = client.get("/api/codeup/repositories")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["error"] == "codeup_not_configured"


def test_list_repositories_returns_503_on_api_error(codeup_app: FastAPI) -> None:
    from deerflow.integrations.codeup.client import CodeupAPIError

    mock_client = MagicMock()
    mock_client.list_repositories = AsyncMock(side_effect=CodeupAPIError("Connection timeout"))

    with patch("app.gateway.routers.codeup.CodeupClient.from_config", return_value=mock_client):
        client = TestClient(codeup_app, raise_server_exceptions=False)
        response = client.get("/api/codeup/repositories")

    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["error"] == "codeup_api_error"

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

# Sample one-page markdown table returned by get_view_detail
_VIEW_DETAIL_ONE_PAGE = """\
——共查询到 2 条结果，总计  1 页。以下是第 1 页明细——
# 视图工作项列表
| 需求文档 | 需求名称 | 工作项 ID | 状态 | 当前负责人 |
| --- | --- | --- | --- | --- |
| https://example.feishu.cn/wiki/abc | 【功能】需求A | 1001 | 进行中 | 张三 |
|  | 【修复】需求B | 1002 | 待排期 |  |
"""

# Column order matches a typical Feishu view export (same keys as feishu_project.view_fields).
_VIEW_DETAIL_ALL_CONFIG_FIELDS = """\
——共查询到 2 条结果，总计  1 页。以下是第 1 页明细——
# 视图工作项列表
| 需求状态 | 需求名称 | 当前负责人 | 优先级 | 工作项 ID | 业务线 | 规划迭代 | 功能模块 | 需求文档 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 开发中 | 【功能】全字段A | ["张三(zhang@example.com)"] | P0 | 7001 | 作家平台/测试 | [{"工作项 ID":"6854567828","工作项名称":"Sprint-A"}] | 书章内容 | https://example.feishu.cn/wiki/full |
| 待排期 | 【功能】全字段B | null | P2 | 7002 |  |  |  |  |
"""


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
# _fetch_requirements_via_mcp unit tests
# ---------------------------------------------------------------------------


def _make_view_tool(return_value: str = _VIEW_DETAIL_ONE_PAGE) -> MagicMock:
    tool = MagicMock()
    tool.name = "feishu_project__get_view_detail"
    tool.invoke.return_value = return_value
    return tool


def test_fetch_requirements_reads_project_key_and_view_id_from_config() -> None:
    """project_key and view_id should be read from config.yaml."""
    from deerflow.config.feishu_project_config import FeishuProjectConfig

    mock_config = MagicMock()
    mock_config.feishu_project = FeishuProjectConfig(project_key="test-proj-key", view_id="test-view-id")

    mock_tool = _make_view_tool()

    with patch("app.gateway.routers.lark.get_app_config", return_value=mock_config):
        with patch("app.gateway.routers.lark.get_cached_mcp_tools", return_value=[mock_tool]):
            import asyncio

            from app.gateway.routers.lark import _fetch_requirements_via_mcp

            asyncio.run(_fetch_requirements_via_mcp())

    mock_tool.invoke.assert_called_once()
    call_args = mock_tool.invoke.call_args[0][0]
    assert call_args["project_key"] == "test-proj-key"
    assert call_args["view_id"] == "test-view-id"


def test_fetch_requirements_returns_empty_when_no_view_id() -> None:
    """When view_id is not configured, returns empty list without calling the tool."""
    from deerflow.config.feishu_project_config import FeishuProjectConfig

    mock_config = MagicMock()
    mock_config.feishu_project = FeishuProjectConfig(project_key="proj-key", view_id="")

    mock_tool = _make_view_tool()

    with patch("app.gateway.routers.lark.get_app_config", return_value=mock_config):
        with patch("app.gateway.routers.lark.get_cached_mcp_tools", return_value=[mock_tool]):
            import asyncio

            from app.gateway.routers.lark import _fetch_requirements_via_mcp

            result = asyncio.run(_fetch_requirements_via_mcp())

    assert result == []
    mock_tool.invoke.assert_not_called()


def test_fetch_requirements_view_fields_passed_to_tool() -> None:
    """view_fields from config are forwarded to get_view_detail."""
    from deerflow.config.feishu_project_config import FeishuProjectConfig

    custom_fields = ["工作项ID", "名称", "wiki"]
    mock_config = MagicMock()
    mock_config.feishu_project = FeishuProjectConfig(
        project_key="proj-key",
        view_id="view-id",
        view_fields=custom_fields,
    )

    mock_tool = _make_view_tool()

    with patch("app.gateway.routers.lark.get_app_config", return_value=mock_config):
        with patch("app.gateway.routers.lark.get_cached_mcp_tools", return_value=[mock_tool]):
            import asyncio

            from app.gateway.routers.lark import _fetch_requirements_via_mcp

            asyncio.run(_fetch_requirements_via_mcp())

    call_args = mock_tool.invoke.call_args[0][0]
    assert call_args["fields"] == custom_fields


def test_fetch_requirements_falls_back_to_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """project_key and view_id should fall back to env vars when config is empty."""
    from deerflow.config.feishu_project_config import FeishuProjectConfig

    mock_config = MagicMock()
    mock_config.feishu_project = FeishuProjectConfig(project_key="", view_id="")

    monkeypatch.setenv("FEISHU_PROJECT_KEY", "env-proj-key")
    monkeypatch.setenv("FEISHU_PROJECT_VIEW_ID", "env-view-id")

    mock_tool = _make_view_tool()

    with patch("app.gateway.routers.lark.get_app_config", return_value=mock_config):
        with patch("app.gateway.routers.lark.get_cached_mcp_tools", return_value=[mock_tool]):
            import asyncio

            from app.gateway.routers.lark import _fetch_requirements_via_mcp

            asyncio.run(_fetch_requirements_via_mcp())

    mock_tool.invoke.assert_called_once()
    call_args = mock_tool.invoke.call_args[0][0]
    assert call_args["project_key"] == "env-proj-key"
    assert call_args["view_id"] == "env-view-id"


def test_fetch_requirements_returns_empty_when_no_project_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns empty list (no error) when project_key is missing from both config and env."""
    from deerflow.config.feishu_project_config import FeishuProjectConfig

    mock_config = MagicMock()
    mock_config.feishu_project = FeishuProjectConfig(project_key="", view_id="some-view")
    monkeypatch.delenv("FEISHU_PROJECT_KEY", raising=False)

    with patch("app.gateway.routers.lark.get_app_config", return_value=mock_config):
        import asyncio

        from app.gateway.routers.lark import _fetch_requirements_via_mcp

        result = asyncio.run(_fetch_requirements_via_mcp())

    assert result == []


# ---------------------------------------------------------------------------
# _parse_view_detail_response unit tests
# ---------------------------------------------------------------------------


def test_parse_view_detail_response_extracts_requirements() -> None:
    """Parser should extract id, title, doc_url, status, assignee from markdown table."""
    from app.gateway.routers.lark import _parse_view_detail_response

    items, total_pages = _parse_view_detail_response(_VIEW_DETAIL_ONE_PAGE)

    assert total_pages == 1
    assert len(items) == 2

    first = items[0]
    assert first.id == "1001"
    assert first.title == "【功能】需求A"
    assert first.doc_url == "https://example.feishu.cn/wiki/abc"
    assert first.status == "进行中"
    assert first.assignee == "张三"

    second = items[1]
    assert second.id == "1002"
    assert second.title == "【修复】需求B"
    assert second.doc_url is None  # empty cell → None
    assert second.assignee is None  # empty cell → None


def test_parse_view_detail_response_coerces_mcp_text_content_blocks() -> None:
    """MCP may return a list of {type, text} blocks; str(list) breaks newline-based parsing."""
    from app.gateway.routers.lark import _parse_view_detail_response

    wrapped = [{"type": "text", "text": _VIEW_DETAIL_ONE_PAGE}]
    items, total_pages = _parse_view_detail_response(wrapped)

    assert total_pages == 1
    assert len(items) == 2
    assert items[0].id == "1001"
    assert items[0].title == "【功能】需求A"


def test_parse_view_detail_response_coerces_nested_content_key() -> None:
    from app.gateway.routers.lark import _parse_view_detail_response

    wrapped = {"content": [{"type": "text", "text": _VIEW_DETAIL_ONE_PAGE}]}
    items, _ = _parse_view_detail_response(wrapped)
    assert len(items) == 2


def test_parse_view_detail_response_maps_all_feishu_view_fields() -> None:
    """All feishu_project.view_fields columns should map into LarkRequirement."""
    from app.gateway.routers.lark import _parse_view_detail_response

    items, _ = _parse_view_detail_response(_VIEW_DETAIL_ALL_CONFIG_FIELDS)
    assert len(items) == 2

    first = items[0]
    assert first.id == "7001"
    assert first.title == "【功能】全字段A"
    assert first.status == "开发中"
    assert first.assignee == '["张三(zhang@example.com)"]'
    assert first.priority == "P0"
    assert first.business_line == "作家平台/测试"
    assert first.iteration == '[{"工作项 ID":"6854567828","工作项名称":"Sprint-A"}]'
    assert first.feature_module == "书章内容"
    assert first.doc_url == "https://example.feishu.cn/wiki/full"

    second = items[1]
    assert second.assignee is None
    assert second.priority == "P2"
    assert second.business_line is None
    assert second.iteration is None
    assert second.feature_module is None
    assert second.doc_url is None


def test_parse_view_detail_response_handles_multipage_header() -> None:
    """Parser should correctly extract total_pages from multi-page header."""
    from app.gateway.routers.lark import _parse_view_detail_response

    text = """\
——共查询到 100 条结果，总计  5 页。以下是第 1 页明细——
# 视图工作项列表
| 需求名称 | 工作项 ID |
| --- | --- |
| 需求X | 9001 |
"""
    items, total_pages = _parse_view_detail_response(text)
    assert total_pages == 5
    assert len(items) == 1
    assert items[0].id == "9001"


def test_parse_view_detail_response_returns_empty_on_none() -> None:
    from app.gateway.routers.lark import _parse_view_detail_response

    items, total_pages = _parse_view_detail_response(None)
    assert items == []
    assert total_pages == 1


def test_parse_view_detail_response_skips_non_http_doc_urls() -> None:
    """Non-HTTP values in the document column should be treated as missing."""
    from app.gateway.routers.lark import _parse_view_detail_response

    text = """\
——共查询到 1 条结果，总计  1 页。以下是第 1 页明细——
| 需求文档 | 需求名称 | 工作项 ID |
| --- | --- | --- |
| 无文档 | 需求Z | 5555 |
"""
    items, _ = _parse_view_detail_response(text)
    assert len(items) == 1
    assert items[0].doc_url is None


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

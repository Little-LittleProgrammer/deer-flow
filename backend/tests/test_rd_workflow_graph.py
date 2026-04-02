"""Unit tests for the R&D Workflow LangGraph nodes and graph."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.rd_workflow.nodes import (
    delivery_node,
    development_node,
    human_approval_node,
    init_workspace_node,
    planning_node,
)
from deerflow.agents.rd_workflow.state import RDWorkflowState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs) -> RDWorkflowState:
    defaults: RDWorkflowState = {
        "messages": [],
        "lark_requirement_id": "REQ-001",
        "work_mode": "planning",
        "codeup_repositories": [],
        "workspace_ready": False,
        "workspaces": [],
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# init_workspace_node
# ---------------------------------------------------------------------------


def test_init_workspace_node_no_repos() -> None:
    state = _make_state(codeup_repositories=[])
    result = asyncio.run(init_workspace_node(state))
    assert result["workspace_ready"] is True
    assert result["workspaces"] == []
    assert len(result["messages"]) == 1


def test_init_workspace_node_missing_config() -> None:
    from deerflow.config.codeup_config import CodeupConfig

    mock_config = MagicMock()
    mock_config.codeup = CodeupConfig(token="", domain="", clone_url_template="")

    state = _make_state(codeup_repositories=["my-repo"])
    with patch("deerflow.config.get_app_config", return_value=mock_config):
        result = asyncio.run(init_workspace_node(state))

    assert result["workspace_ready"] is False
    assert "not configured" in result["workspace_error"]


# ---------------------------------------------------------------------------
# planning_node
# ---------------------------------------------------------------------------


def test_planning_node_development_mode_skips() -> None:
    state = _make_state(work_mode="development")
    result = asyncio.run(planning_node(state))
    assert result["planning_complete"] is True
    assert "Skipping planning" in result["messages"][0].content


def test_planning_node_planning_mode_generates_prompt() -> None:
    state = _make_state(
        work_mode="planning",
        workspaces=[{"repo_name": "backend", "physical_path": "/tmp/ws/backend", "branch": "feature/REQ-001", "cloned": True}],
    )
    result = asyncio.run(planning_node(state))
    assert result["planning_complete"] is True
    assert "technical_design" in result
    assert len(result["messages"]) >= 1


# ---------------------------------------------------------------------------
# human_approval_node
# ---------------------------------------------------------------------------


def test_human_approval_node_approved_state() -> None:
    state = _make_state(approval_status="approved")
    with patch("deerflow.agents.rd_workflow.nodes.interrupt") as mock_interrupt:
        result = human_approval_node(state)
    assert result["approval_status"] == "approved"
    mock_interrupt.assert_not_called()
    assert "approved" in result["messages"][0].content.lower()


def test_human_approval_node_rejected_state() -> None:
    state = _make_state(approval_status="rejected")
    with patch("deerflow.agents.rd_workflow.nodes.interrupt") as mock_interrupt:
        result = human_approval_node(state)
    assert result["approval_status"] == "rejected"
    mock_interrupt.assert_not_called()


def test_human_approval_node_triggers_interrupt() -> None:
    from langgraph.errors import GraphInterrupt

    state = _make_state(approval_status=None)
    with pytest.raises((GraphInterrupt, Exception)):
        human_approval_node(state)


def test_human_approval_node_resume_approved() -> None:
    """When interrupt() returns 'approved', the node transitions to approved."""
    state = _make_state(approval_status=None)
    with patch("deerflow.agents.rd_workflow.nodes.interrupt", return_value="approved") as mock_interrupt:
        result = human_approval_node(state)
    mock_interrupt.assert_called_once()
    assert result["approval_status"] == "approved"
    assert "approved" in result["messages"][0].content.lower()


def test_human_approval_node_resume_rejected() -> None:
    """When interrupt() returns 'rejected', the node transitions to rejected."""
    state = _make_state(approval_status=None)
    with patch("deerflow.agents.rd_workflow.nodes.interrupt", return_value="rejected") as mock_interrupt:
        result = human_approval_node(state)
    mock_interrupt.assert_called_once()
    assert result["approval_status"] == "rejected"
    assert "rejected" in result["messages"][0].content.lower()


def test_human_approval_node_resume_dict_approved() -> None:
    """When interrupt() returns {'approval': 'approved'}, the node transitions to approved."""
    state = _make_state(approval_status=None)
    with patch(
        "deerflow.agents.rd_workflow.nodes.interrupt",
        return_value={"approval": "approved"},
    ):
        result = human_approval_node(state)
    assert result["approval_status"] == "approved"


# ---------------------------------------------------------------------------
# development_node
# ---------------------------------------------------------------------------


def test_development_node_no_workspaces() -> None:
    state = _make_state(workspaces=[])
    result = asyncio.run(development_node(state))
    assert result["development_complete"] is True
    assert result["committed_tasks"] == []


def test_development_node_with_workspace() -> None:
    state = _make_state(
        workspaces=[{"repo_name": "backend", "physical_path": "/tmp/nonexistent", "branch": "feature/REQ-001", "cloned": True}],
    )
    with patch("deerflow.agents.rd_workflow.nodes._framework_git_commit") as mock_commit:
        mock_commit.return_value = None
        result = asyncio.run(development_node(state))

    assert result["development_complete"] is True


# ---------------------------------------------------------------------------
# delivery_node
# ---------------------------------------------------------------------------


def test_delivery_node_no_workspaces() -> None:
    state = _make_state(workspaces=[])
    result = asyncio.run(delivery_node(state))
    assert result["delivery_complete"] is True
    assert result["mr_urls"] == []


def test_delivery_node_codeup_not_configured() -> None:
    from deerflow.integrations.codeup.client import CodeupConfigurationError

    state = _make_state(workspaces=[{"repo_name": "backend", "physical_path": "/tmp/ws", "branch": "feature/REQ-001", "cloned": True}])
    with patch("deerflow.integrations.codeup.client.CodeupClient.from_config", side_effect=CodeupConfigurationError("CODEUP_TOKEN not set")):
        result = asyncio.run(delivery_node(state))

    assert result["delivery_complete"] is False
    assert result["delivery_error"] is not None


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------


def test_make_rd_workflow_graph_compiles() -> None:
    from deerflow.agents.rd_workflow.graph import make_rd_workflow_graph

    graph = make_rd_workflow_graph()
    assert graph is not None


def test_graph_has_correct_nodes() -> None:
    from deerflow.agents.rd_workflow.graph import make_rd_workflow_graph

    graph = make_rd_workflow_graph()
    node_names = set(graph.nodes.keys())
    expected = {"init_workspace_node", "planning_node", "human_approval_node", "development_node", "delivery_node"}
    assert expected.issubset(node_names)

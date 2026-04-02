"""R&D Workflow LangGraph StateGraph definition.

Graph topology:
  init_workspace_node → planning_node → human_approval_node → development_node → delivery_node

Triggered when a thread is created with metadata:
  {"type": "lark_requirement_task", "lark_requirement_id": "...", "work_mode": "...", "codeup_repositories": [...]}

Human-in-the-loop: human_approval_node calls interrupt() to pause execution.
Resume via: POST /threads/{thread_id}/runs with:
  {"as_node": "human_approval_node", "values": {"approval": "approved"}}
"""

from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from .nodes import (
    delivery_node,
    development_node,
    human_approval_node,
    init_workspace_node,
    planning_node,
)
from .state import RDWorkflowState

logger = logging.getLogger(__name__)


def _route_after_approval(state: RDWorkflowState) -> str:
    """Route after human_approval_node based on approval status."""
    approval = state.get("approval_status")
    if approval == "rejected":
        return END
    return "development_node"


def make_rd_workflow_graph(config: RunnableConfig | None = None) -> StateGraph:
    """Create the compiled R&D Workflow StateGraph.

    This graph is registered in langgraph.json as "rd_workflow" and routed
    to when thread metadata contains type="lark_requirement_task".

    Args:
        config: Optional RunnableConfig (unused, kept for registration signature parity).

    Returns:
        Compiled StateGraph ready for LangGraph Server.
    """
    builder = StateGraph(RDWorkflowState)

    # Register nodes
    builder.add_node("init_workspace_node", init_workspace_node)
    builder.add_node("planning_node", planning_node)
    builder.add_node("human_approval_node", human_approval_node)
    builder.add_node("development_node", development_node)
    builder.add_node("delivery_node", delivery_node)

    # Define edges
    builder.add_edge(START, "init_workspace_node")
    builder.add_edge("init_workspace_node", "planning_node")
    builder.add_edge("planning_node", "human_approval_node")
    builder.add_conditional_edges(
        "human_approval_node",
        _route_after_approval,
        {"development_node": "development_node", END: END},
    )
    builder.add_edge("development_node", "delivery_node")
    builder.add_edge("delivery_node", END)

    return builder.compile()

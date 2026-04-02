"""State schema for the R&D Workflow LangGraph."""

from typing import Annotated, Literal, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class WorkspaceInfo(TypedDict):
    """Information about a cloned repository workspace."""

    repo_name: str
    physical_path: str
    branch: str
    cloned: bool


class RDWorkflowState(TypedDict):
    """State for the R&D Workflow graph.

    Carries metadata from the dispatch trigger through all nodes.
    """

    messages: Annotated[list[BaseMessage], add_messages]

    # --- Trigger metadata (injected via POST /api/threads metadata) ---
    lark_requirement_id: NotRequired[str | None]
    work_mode: NotRequired[Literal["planning", "development"] | None]
    codeup_repositories: NotRequired[list[str] | None]

    # --- init_workspace_node outputs ---
    workspace_ready: NotRequired[bool]
    workspaces: NotRequired[list[WorkspaceInfo] | None]
    workspace_error: NotRequired[str | None]

    # --- planning_node outputs ---
    planning_complete: NotRequired[bool]
    technical_design: NotRequired[str | None]

    # --- human_approval_node ---
    approval_status: NotRequired[Literal["pending", "approved", "rejected"] | None]

    # --- development_node outputs ---
    development_complete: NotRequired[bool]
    committed_tasks: NotRequired[list[str] | None]

    # --- delivery_node outputs ---
    mr_urls: NotRequired[list[str] | None]
    delivery_complete: NotRequired[bool]
    delivery_error: NotRequired[str | None]

"""Lark (Feishu) integration API routes.

Provides REST endpoints to proxy Feishu Project requirements data
from FeishuProjectMcp Streamable HTTP server.
"""

import json
import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lark", tags=["lark"])

# Tool name used to query work items via MQL (provided by FeishuProjectMcp)
_SEARCH_TOOL_NAME = "search_by_mql"


class LarkRequirement(BaseModel):
    """A single Feishu Project requirement (work item)."""

    id: str = Field(..., description="Work item unique ID")
    title: str = Field(..., description="Work item title")
    status: str = Field(default="", description="Current status label")
    type: str = Field(default="", description="Work item type (e.g., requirement, bug)")
    assignee: str | None = Field(default=None, description="Assignee display name")
    doc_url: str | None = Field(default=None, description="Associated Feishu document URL")
    iteration: str | None = Field(default=None, description="Iteration/sprint label")


class LarkRequirementsResponse(BaseModel):
    """Response model for the requirements list endpoint."""

    requirements: list[LarkRequirement]
    total: int


async def _fetch_requirements_via_mcp(iteration_id: str | None = None) -> list[LarkRequirement]:
    """Fetch requirements from FeishuProjectMcp via LangChain MCP adapter.

    Uses the ``search_by_mql`` tool (Streamable HTTP / 2025-03-26 protocol).
    Requires the environment variable ``FEISHU_PROJECT_KEY`` to be set.

    Raises:
        RuntimeError: If FeishuProjectMcp is not configured or unreachable.
    """
    from deerflow.mcp.cache import get_cached_mcp_tools

    project_key = os.environ.get("FEISHU_PROJECT_KEY", "")
    if not project_key:
        logger.warning("FEISHU_PROJECT_KEY not set; returning empty requirements list")
        return []

    try:
        tools = get_cached_mcp_tools()
    except Exception as e:
        raise RuntimeError(f"Failed to load MCP tools: {e}") from e

    # FeishuProjectMcp tools are prefixed with the server name by langchain-mcp-adapters
    search_tool = next(
        (t for t in tools if t.name.endswith(_SEARCH_TOOL_NAME)),
        None,
    )

    if search_tool is None:
        logger.warning("FeishuProjectMcp search_by_mql tool not found; returning empty requirements list")
        return []

    try:
        args: dict = {"project_key": project_key}
        if iteration_id:
            # Filter by iteration using MQL
            args["mql"] = f"iteration = '{iteration_id}'"
        raw = search_tool.invoke(args)
        return _parse_search_response(raw)
    except Exception as e:
        raise RuntimeError(f"FeishuProjectMcp call failed: {e}") from e


def _parse_search_response(raw: object) -> list[LarkRequirement]:
    """Parse search_by_mql response into a list of LarkRequirement objects."""
    if raw is None:
        return []

    # raw may be a JSON string, a dict, or a list depending on the MCP adapter version
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("search_by_mql returned non-JSON string: %s", raw[:200])
            return []

    items: list = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        # Common response shapes: {"data": [...]} or {"items": [...]} or {"work_items": [...]}
        for key in ("data", "items", "work_items", "results"):
            if key in raw and isinstance(raw[key], list):
                items = raw[key]
                break

    return [_parse_requirement(item) for item in items if isinstance(item, dict)]


def _parse_requirement(item: dict) -> LarkRequirement:
    """Parse a raw MCP tool response item into a LarkRequirement."""
    return LarkRequirement(
        id=str(item.get("id", item.get("work_item_id", ""))),
        title=item.get("title", item.get("name", "")),
        status=item.get("status", item.get("state", "")),
        type=item.get("type", item.get("work_item_type", "")),
        assignee=item.get("assignee", item.get("owner")),
        doc_url=item.get("doc_url", item.get("document_url")),
        iteration=item.get("iteration", item.get("sprint")),
    )


@router.get(
    "/requirements",
    response_model=LarkRequirementsResponse,
    summary="Get Feishu Project Requirements",
    description=("Fetch the current iteration's requirement work items from Feishu Project via FeishuProjectMcp. Requires FEISHU_MCP_TOKEN to be set."),
)
async def get_requirements(iteration: str | None = None) -> LarkRequirementsResponse:
    """Pull requirements from Feishu Project MCP.

    Args:
        iteration: Optional iteration ID to filter results.

    Returns:
        List of requirement work items.

    Raises:
        HTTPException 503: If FeishuProjectMcp is unavailable after retries.
    """
    try:
        requirements = await _fetch_requirements_via_mcp(iteration_id=iteration)
        return LarkRequirementsResponse(requirements=requirements, total=len(requirements))
    except RuntimeError as e:
        logger.error("FeishuProjectMcp unavailable: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"error": "feishu_mcp_unavailable", "message": str(e)},
        ) from e

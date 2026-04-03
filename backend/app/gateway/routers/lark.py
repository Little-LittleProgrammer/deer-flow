"""Lark (Feishu) integration API routes.

Provides REST endpoints to proxy Feishu Project requirements data
from FeishuProjectMcp Streamable HTTP server.
"""

import logging
import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config import get_app_config
from deerflow.mcp.cache import get_cached_mcp_tools

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lark", tags=["lark"])

# Tool name used to query work items by view (provided by FeishuProjectMcp)
_VIEW_TOOL_NAME = "get_view_detail"


class LarkRequirement(BaseModel):
    """A single Feishu Project requirement (work item).

    Fields align with ``feishu_project.view_fields`` in config (e.g. 工作项ID、规划迭代、
    业务线、功能模块、需求名称、需求文档、需求状态、当前负责人、优先级).
    """

    id: str = Field(..., description="Work item unique ID (工作项ID)")
    title: str = Field(..., description="Work item title (需求名称)")
    status: str = Field(default="", description="Requirement status (需求状态)")
    type: str = Field(default="", description="Work item type (optional; not in default view_fields)")
    assignee: str | None = Field(default=None, description="Current owners (当前负责人), raw cell text")
    doc_url: str | None = Field(default=None, description="Requirement doc URL (需求文档)")
    iteration: str | None = Field(default=None, description="Planned iteration (规划迭代), raw cell text")
    business_line: str | None = Field(default=None, description="Business line (业务线)")
    feature_module: str | None = Field(default=None, description="Feature module (功能模块)")
    priority: str | None = Field(default=None, description="Priority label (优先级)")


class LarkRequirementsResponse(BaseModel):
    """Response model for the requirements list endpoint."""

    requirements: list[LarkRequirement]
    total: int


async def _fetch_requirements_via_mcp(iteration_id: str | None = None) -> list[LarkRequirement]:
    """Fetch requirements from FeishuProjectMcp via LangChain MCP adapter.

    Uses the ``get_view_detail`` tool (Streamable HTTP / 2025-03-26 protocol)
    to retrieve all work items belonging to the configured view.

    Reads ``project_key``, ``view_id`` and ``view_fields`` from ``config.yaml``
    (``feishu_project.*``), with env-var fallbacks::

        FEISHU_PROJECT_KEY  → project_key
        FEISHU_PROJECT_VIEW_ID → view_id

    ``get_view_detail`` returns a markdown-formatted table; the response is
    parsed by :func:`_parse_view_detail_response` which maps column headers to
    :class:`LarkRequirement` fields using fuzzy header matching.

    Args:
        iteration_id: Accepted for API compatibility but not applied to the
            view-based query (the view's own filters already scope the results).

    Raises:
        RuntimeError: If FeishuProjectMcp is not configured or unreachable.
    """
    if iteration_id:
        logger.debug(
            "iteration_id=%r ignored: get_view_detail uses the view's own filters",
            iteration_id,
        )

    feishu_cfg = get_app_config().feishu_project
    project_key = feishu_cfg.project_key or os.environ.get("FEISHU_PROJECT_KEY", "")
    view_id = feishu_cfg.view_id or os.environ.get("FEISHU_PROJECT_VIEW_ID", "")

    if not project_key:
        logger.warning(
            "feishu_project.project_key not configured (config.yaml) and "
            "FEISHU_PROJECT_KEY env var not set; returning empty requirements list"
        )
        return []

    if not view_id:
        logger.warning(
            "feishu_project.view_id not configured (config.yaml) and "
            "FEISHU_PROJECT_VIEW_ID env var not set; returning empty requirements list"
        )
        return []

    try:
        tools = get_cached_mcp_tools()
    except Exception as e:
        raise RuntimeError(f"Failed to load MCP tools: {e}") from e

    view_tool = next(
        (t for t in tools if t.name.endswith(_VIEW_TOOL_NAME)),
        None,
    )

    if view_tool is None:
        all_tool_names = [t.name for t in tools]
        logger.warning(
            "FeishuProjectMcp get_view_detail tool not found; available tools: %s",
            all_tool_names,
        )
        return []

    requirements: list[LarkRequirement] = []
    page_num = 1
    total_pages = 1

    try:
        while page_num <= total_pages:
            args: dict = {
                "project_key": project_key,
                "view_id": view_id,
                "fields": feishu_cfg.view_fields,
                "page_num": page_num,
            }
            logger.info("get_view_detail call args: %s", args)
            raw = view_tool.invoke(args)
            logger.info(
                "get_view_detail raw response (type=%s, len=%s): %r",
                type(raw).__name__,
                len(str(raw)) if raw is not None else 0,
                str(raw)[:2000],
            )
            page_items, total_pages = _parse_view_detail_response(raw)
            logger.info("page %d/%d parsed %d items", page_num, total_pages, len(page_items))
            requirements.extend(page_items)
            if page_num >= total_pages:
                break
            page_num += 1
    except Exception as e:
        raise RuntimeError(f"FeishuProjectMcp call failed: {e}") from e

    logger.info("total requirements fetched: %d", len(requirements))
    return requirements


def _coerce_view_detail_markdown(raw: object) -> str:
    """Turn MCP ``get_view_detail`` tool output into a markdown string.

    LangChain / MCP often returns a list of content blocks like
    ``[{"type": "text", "text": "...markdown..."}]``. Using :func:`str` on that
    produces a single-line Python repr where newlines are escaped, so table
    rows never match ``line.startswith("|")``. This helper extracts real text.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    # ToolMessage / AIMessage-style
    content = getattr(raw, "content", None)
    if content is not None and not isinstance(raw, dict):
        return _coerce_view_detail_markdown(content)
    if isinstance(raw, dict):
        t = raw.get("text")
        if isinstance(t, str):
            return t
        c = raw.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return _coerce_view_detail_markdown(c)
        return ""
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            chunk = _coerce_view_detail_markdown(item)
            if chunk:
                parts.append(chunk)
        return "\n".join(parts)
    return str(raw) if raw else ""


def _parse_view_detail_response(raw: object) -> tuple[list[LarkRequirement], int]:
    """Parse get_view_detail markdown table response.

    Returns:
        Tuple of (requirements list, total page count).
    """
    if raw is None:
        logger.info("_parse_view_detail_response: raw is None, returning empty")
        return [], 1

    text = _coerce_view_detail_markdown(raw)

    # Extract total page count from header line, e.g. "总计  3 页"
    total_pages = 1
    pages_match = re.search(r"总计\s*(\d+)\s*页", text)
    if pages_match:
        total_pages = int(pages_match.group(1))

    # Collect only markdown table lines
    table_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    logger.info("_parse_view_detail_response: table_lines count=%d, total_pages=%d", len(table_lines), total_pages)

    if len(table_lines) < 3:  # need header + separator + at least one data row
        logger.warning(
            "_parse_view_detail_response: not enough table lines (%d), full text: %r",
            len(table_lines),
            text[:500],
        )
        return [], total_pages

    headers = [h.strip() for h in table_lines[0].split("|")[1:-1]]
    logger.info("_parse_view_detail_response: headers=%s", headers)
    # table_lines[1] is the separator row (| --- | --- | ...)

    def find_col(patterns: list[str]) -> int | None:
        for i, h in enumerate(headers):
            h_norm = h.strip().lower().replace(" ", "")
            for pattern in patterns:
                p_norm = pattern.lower().replace(" ", "")
                if p_norm in h_norm or pattern.lower() in h.lower():
                    return i
        return None

    id_col = find_col(["工作项id", "工作项 id", "work_item_id"])
    name_col = find_col(["需求名称", "名称", "name", "title"])
    doc_col = find_col(["需求文档", "文档", "wiki"])
    status_col = find_col(["需求状态", "状态", "status"])
    assignee_col = find_col(["当前负责人", "负责人", "assignee", "owner"])
    iteration_col = find_col(["规划迭代", "迭代", "iteration", "sprint"])
    business_line_col = find_col(["业务线"])
    feature_module_col = find_col(["功能模块", "模块"])
    priority_col = find_col(["优先级", "priority"])

    def get_col(cols: list[str], col_idx: int | None) -> str:
        if col_idx is None or col_idx >= len(cols):
            return ""
        return cols[col_idx]

    def optional_cell(raw: str) -> str | None:
        v = raw.strip()
        if not v or v.lower() == "null":
            return None
        return v

    requirements: list[LarkRequirement] = []
    for line in table_lines[2:]:
        cols = [c.strip() for c in line.split("|")[1:-1]]

        item_id = get_col(cols, id_col)
        title = get_col(cols, name_col)

        if not item_id and not title:
            continue

        doc_url_val = get_col(cols, doc_col)

        requirements.append(
            LarkRequirement(
                id=item_id,
                title=title,
                status=get_col(cols, status_col),
                doc_url=doc_url_val if doc_url_val.startswith("http") else None,
                assignee=optional_cell(get_col(cols, assignee_col) or ""),
                iteration=optional_cell(get_col(cols, iteration_col) or ""),
                business_line=optional_cell(get_col(cols, business_line_col) or ""),
                feature_module=optional_cell(get_col(cols, feature_module_col) or ""),
                priority=optional_cell(get_col(cols, priority_col) or ""),
            )
        )

    return requirements, total_pages


@router.get(
    "/requirements",
    response_model=LarkRequirementsResponse,
    summary="Get Feishu Project Requirements",
    description=(
        "Fetch requirement work items from Feishu Project via FeishuProjectMcp. "
        "Uses get_view_detail to retrieve all items in the configured view "
        "(feishu_project.view_id in config.yaml). "
        "Requires FEISHU_MCP_TOKEN to be set."
    ),
)
async def get_requirements(iteration: str | None = None) -> LarkRequirementsResponse:
    """Pull requirements from Feishu Project MCP.

    Args:
        iteration: Optional iteration label (accepted for compatibility;
            filtering is delegated to the view's own configuration).

    Returns:
        List of requirement work items.

    Raises:
        HTTPException 503: If FeishuProjectMcp is unavailable.
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

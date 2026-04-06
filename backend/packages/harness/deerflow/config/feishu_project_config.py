"""Feishu Project integration configuration."""

from pydantic import BaseModel, Field


class FeishuProjectConfig(BaseModel):
    """Configuration for Feishu Project (飞书项目) integration.

    Used by the requirements list API (``/api/lark/requirements``) to query
    work items via the ``get_view_detail`` tool provided by FeishuProjectMcp.

    The ``project_key`` and ``view_id`` can be extracted from a Feishu Project
    view URL::

        https://project.feishu.cn/{project_key}/storyView/{view_id}
    """

    project_key: str = Field(
        default="",
        description=("Feishu Project space key (simpleName or numeric key). Extract from URL: https://project.feishu.cn/{project_key}/..."),
    )
    view_id: str = Field(
        default="",
        description=("View ID used to fetch requirement work items via get_view_detail. Extract from URL: https://project.feishu.cn/.../storyView/{view_id}"),
    )
    view_fields: list[str] = Field(
        default=["工作项ID", "名称", "wiki", "状态", "当前负责人"],
        description=("Fields to retrieve from the view. Accepts field keys (e.g. 'wiki', 'name') or display names (e.g. '需求名称'). The 'wiki' key maps to the 需求文档 link field."),
    )

    def is_configured(self) -> bool:
        """Return True if the minimum required fields are configured."""
        return bool(self.project_key and self.view_id)

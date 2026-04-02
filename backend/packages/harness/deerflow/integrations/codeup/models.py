"""Codeup API response models."""

from pydantic import BaseModel, Field


class Repository(BaseModel):
    """Codeup repository information."""

    id: int = Field(..., description="Repository ID")
    name: str = Field(..., description="Repository name")
    path: str = Field(..., description="Repository path")
    path_with_namespace: str = Field(..., alias="pathWithNamespace", description="Full path including namespace")
    description: str | None = Field(default=None, description="Repository description")
    visibility: str = Field(default="private", description="Visibility: private / internal / public")
    web_url: str = Field(..., alias="webUrl", description="Web URL of the repository")
    archived: bool = Field(default=False, description="Whether the repository is archived")

    model_config = {"populate_by_name": True}


class ChangeRequest(BaseModel):
    """Codeup merge request (change request) information."""

    local_id: int = Field(..., alias="localId", description="Local ID of the MR within the repository")
    title: str = Field(..., description="MR title")
    description: str | None = Field(default=None, description="MR description")
    status: str = Field(..., description="MR status: UNDER_DEV / UNDER_REVIEW / TO_BE_MERGED / CLOSED / MERGED")
    source_branch: str = Field(..., alias="sourceBranch", description="Source branch")
    target_branch: str = Field(..., alias="targetBranch", description="Target branch")
    web_url: str = Field(..., alias="webUrl", description="Web URL of the MR detail page")
    detail_url: str = Field(..., alias="detailUrl", description="Detail URL of the MR")
    project_id: int = Field(..., alias="projectId", description="Repository ID")

    model_config = {"populate_by_name": True}

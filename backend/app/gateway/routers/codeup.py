"""Codeup integration API routes.

Provides REST endpoints for listing Codeup repositories
using the CodeupClient.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.integrations.codeup.client import CodeupClient, CodeupConfigurationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/codeup", tags=["codeup"])


class CodeupRepositoryResponse(BaseModel):
    """A single Codeup repository entry."""

    id: int = Field(..., description="Repository integer ID")
    name: str = Field(..., description="Repository name")
    path: str = Field(..., description="Repository path")
    path_with_namespace: str = Field(..., description="Full path including namespace")
    description: str | None = Field(default=None, description="Repository description")
    visibility: str = Field(default="private", description="Visibility level")
    web_url: str = Field(..., description="Web URL of the repository")
    archived: bool = Field(default=False, description="Whether the repository is archived")


class CodeupRepositoriesResponse(BaseModel):
    """Response model for the repositories list endpoint."""

    repositories: list[CodeupRepositoryResponse]
    total: int


@router.get(
    "/repositories",
    response_model=CodeupRepositoriesResponse,
    summary="List Codeup Repositories",
    description=("Fetch accessible Codeup repositories using the configured CODEUP_TOKEN. Returns 503 if the token is not configured."),
)
async def list_repositories(search: str | None = None) -> CodeupRepositoriesResponse:
    """List Codeup repositories accessible with the configured PAT.

    Args:
        search: Optional fuzzy search keyword to filter repositories.

    Returns:
        List of accessible repositories.

    Raises:
        HTTPException 503: If Codeup is not configured or API is unreachable.
    """
    try:
        client = CodeupClient.from_config()
    except CodeupConfigurationError as e:
        raise HTTPException(
            status_code=503,
            detail={"error": "codeup_not_configured", "message": str(e)},
        ) from e

    try:
        repos = await client.list_repositories(search=search)
        result = [
            CodeupRepositoryResponse(
                id=r.id,
                name=r.name,
                path=r.path,
                path_with_namespace=r.path_with_namespace,
                description=r.description,
                visibility=r.visibility,
                web_url=r.web_url,
                archived=r.archived,
            )
            for r in repos
        ]
        return CodeupRepositoriesResponse(repositories=result, total=len(result))
    except Exception as e:
        logger.error("Codeup API error: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"error": "codeup_api_error", "message": str(e)},
        ) from e

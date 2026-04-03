"""Codeup integration configuration."""

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CodeupConfig(BaseModel):
    """Configuration for Alibaba Cloud Codeup integration.

    Used by the R&D workflow for repository cloning, branch management, and MR creation.
    """

    model_config = ConfigDict(extra="ignore")

    token: str = Field(
        default="",
        validation_alias=AliasChoices("token", "yunxiao_token"),
        description="Codeup Personal Access Token (x-yunxiao-token). Set via CODEUP_TOKEN env var, or yunxiao_token under enterprise_connectors.codeup.",
    )
    domain: str = Field(
        default="",
        description="Codeup API domain (without protocol prefix). Set via CODEUP_DOMAIN env var.",
    )
    organization_id: str | None = Field(
        default=None,
        description="Organization ID required for central-edition Codeup (optional for Region edition).",
    )
    clone_url_template: str = Field(
        default="",
        description=("HTTPS clone URL template with PAT embedded. Example: https://{token}@{domain}/{org}/{repo}.git. Set via CODEUP_CLONE_URL_TEMPLATE env var."),
    )

    def is_configured(self) -> bool:
        """Return True if the minimum required fields are configured."""
        return bool(self.token and self.domain)

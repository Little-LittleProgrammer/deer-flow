"""Security helpers for sandbox capability gating."""

import re

from deerflow.config import get_app_config

_LOCAL_SANDBOX_PROVIDER_MARKERS = (
    "deerflow.sandbox.local:LocalSandboxProvider",
    "deerflow.sandbox.local.local_sandbox_provider:LocalSandboxProvider",
)

LOCAL_HOST_BASH_DISABLED_MESSAGE = (
    "Host bash execution is disabled for LocalSandboxProvider because it is not a secure "
    "sandbox boundary. Switch to AioSandboxProvider for isolated bash access, or set "
    "sandbox.allow_host_bash: true only in a fully trusted local environment."
)

LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE = (
    "Bash subagent is disabled for LocalSandboxProvider because host bash execution is not "
    "a secure sandbox boundary. Switch to AioSandboxProvider for isolated bash access, or "
    "set sandbox.allow_host_bash: true only in a fully trusted local environment."
)


def uses_local_sandbox_provider(config=None) -> bool:
    """Return True when the active sandbox provider is the host-local provider."""
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    sandbox_use = getattr(sandbox_cfg, "use", "")
    if sandbox_use in _LOCAL_SANDBOX_PROVIDER_MARKERS:
        return True
    return sandbox_use.endswith(":LocalSandboxProvider") and "deerflow.sandbox.local" in sandbox_use


def is_host_bash_allowed(config=None) -> bool:
    """Return whether host bash execution is explicitly allowed."""
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    if sandbox_cfg is None:
        return False
    if not uses_local_sandbox_provider(config):
        return True
    return bool(getattr(sandbox_cfg, "allow_host_bash", False))


# Only block clearly high-risk git usage in the sandbox:
# - push: writes to remotes (exfil / overwrite shared history)
# - clean: can delete large numbers of untracked files (-fd, etc.)
_BLOCKED_HIGH_RISK_GIT_SUBCOMMANDS = frozenset(["push", "clean"])

_GIT_CMD_PATTERN = re.compile(r"(?:^|[;&|]\s*)git\s+(\S+)", re.MULTILINE)

SANDBOX_GIT_HIGH_RISK_MESSAGE = (
    "High-risk git commands (push, clean) are not permitted inside the sandbox. "
    "Push can modify remote repositories; clean can delete many files. "
    "Use other git commands as needed, or perform push/clean outside the agent sandbox."
)

# Backwards-compatible alias (historical name).
SANDBOX_GIT_BLOCKED_MESSAGE = SANDBOX_GIT_HIGH_RISK_MESSAGE


def is_high_risk_git_command(command: str) -> bool:
    """Return True if the command contains a blocked high-risk git subcommand.

    Currently blocks only ``git push`` and ``git clean``. Other git CLI usage is allowed.

    Args:
        command: The bash command string to inspect.

    Returns:
        True if a blocked high-risk git subcommand is present, False otherwise.
    """
    for match in _GIT_CMD_PATTERN.finditer(command):
        subcommand = match.group(1).lstrip("-")
        if subcommand in _BLOCKED_HIGH_RISK_GIT_SUBCOMMANDS:
            return True
    return False


# Backwards-compatible alias (historical name).
is_git_write_command = is_high_risk_git_command


def get_feishu_sandbox_env() -> dict[str, str]:
    """Return Feishu credential environment variables for sandbox injection.

    Reads FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_MCP_TOKEN and optionally
    FEISHU_USER_ACCESS_TOKEN from the host environment and returns them as a dict
    suitable for injection into sandbox container environment variables.

    Only non-empty values are included to avoid injecting empty strings.

    Returns:
        Dictionary of Feishu env var name → value for sandbox injection.
    """
    import os

    feishu_env_keys = [
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_MCP_TOKEN",
        "FEISHU_USER_ACCESS_TOKEN",
    ]
    return {key: val for key in feishu_env_keys if (val := os.getenv(key, ""))}

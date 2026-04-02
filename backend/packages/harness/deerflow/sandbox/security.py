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
        return True
    if not uses_local_sandbox_provider(config):
        return True
    return bool(getattr(sandbox_cfg, "allow_host_bash", False))


# Commands that the Agent must never execute directly in the sandbox.
# Framework-Delegated Git pattern: git commit/push/reset etc. are reserved
# for backend Python nodes, not for LLM-driven agent tool calls.
_BLOCKED_GIT_SUBCOMMANDS = frozenset(
    [
        "commit",
        "push",
        "reset",
        "rebase",
        "merge",
        "cherry-pick",
        "revert",
        "tag",
        "remote",
        "fetch",
        "pull",
        "stash",
        "clean",
        "rm",
    ]
)

_GIT_CMD_PATTERN = re.compile(r"(?:^|[;&|]\s*)git\s+(\S+)", re.MULTILINE)

SANDBOX_GIT_BLOCKED_MESSAGE = (
    "Git write operations (commit, push, reset, rebase, etc.) are not permitted inside the sandbox. "
    "These operations are managed by the framework (Framework-Delegated Git pattern) to ensure "
    "safety and auditability. Use read-only git commands (log, status, diff, show, ls-files) instead."
)


def is_git_write_command(command: str) -> bool:
    """Return True if the command contains a blocked git write subcommand.

    Allows read-only git operations (log, status, diff, show, ls-files, blame, etc.)
    while blocking all write operations.

    Args:
        command: The bash command string to inspect.

    Returns:
        True if the command contains a blocked git subcommand, False otherwise.
    """
    for match in _GIT_CMD_PATTERN.finditer(command):
        subcommand = match.group(1).lstrip("-")
        if subcommand in _BLOCKED_GIT_SUBCOMMANDS:
            return True
    return False


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

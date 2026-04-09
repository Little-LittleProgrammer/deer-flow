"""Tests for Feishu credential transparency and Git CLI blocking in sandbox."""

import os
from unittest.mock import patch

from deerflow.sandbox.security import (
    get_feishu_sandbox_env,
    is_git_write_command,
    is_high_risk_git_command,
)

# ---------------------------------------------------------------------------
# is_high_risk_git_command / is_git_write_command (alias)
# ---------------------------------------------------------------------------


def test_blocks_git_push() -> None:
    assert is_high_risk_git_command("git push origin main") is True


def test_blocks_git_clean() -> None:
    assert is_high_risk_git_command("git clean -fd") is True


def test_allows_git_commit_reset_rebase_merge() -> None:
    assert is_high_risk_git_command("git commit -m 'test'") is False
    assert is_high_risk_git_command("git reset --hard HEAD~1") is False
    assert is_high_risk_git_command("git rebase main") is False
    assert is_high_risk_git_command("git merge feature/foo") is False


def test_allows_git_fetch_pull_remote_rm() -> None:
    assert is_high_risk_git_command("git fetch origin") is False
    assert is_high_risk_git_command("git pull origin main") is False
    assert is_high_risk_git_command("git remote -v") is False
    assert is_high_risk_git_command("git rm foo.txt") is False


def test_allows_git_log() -> None:
    assert is_high_risk_git_command("git log --oneline") is False


def test_allows_git_status() -> None:
    assert is_high_risk_git_command("git status") is False


def test_allows_git_diff() -> None:
    assert is_high_risk_git_command("git diff HEAD") is False


def test_allows_git_show() -> None:
    assert is_high_risk_git_command("git show HEAD:file.py") is False


def test_allows_git_ls_files() -> None:
    assert is_high_risk_git_command("git ls-files") is False


def test_allows_non_git_command() -> None:
    assert is_high_risk_git_command("python tests/test_foo.py") is False
    assert is_high_risk_git_command("ls -la /mnt/user-data/workspace") is False


def test_allows_git_commit_in_chain() -> None:
    assert is_high_risk_git_command("cd /workspace && git commit -m 'done'") is False


def test_blocks_git_push_in_chain() -> None:
    assert is_high_risk_git_command("git add . && git push origin feature/foo") is True


def test_blocks_git_clean_in_chain() -> None:
    assert is_high_risk_git_command("git status && git clean -fd") is True


def test_does_not_block_word_commit_in_echo() -> None:
    assert is_high_risk_git_command("echo 'commit message'") is False


def test_is_git_write_command_is_alias() -> None:
    assert is_git_write_command is is_high_risk_git_command


# ---------------------------------------------------------------------------
# get_feishu_sandbox_env
# ---------------------------------------------------------------------------


def test_get_feishu_sandbox_env_returns_set_vars() -> None:
    env_override = {
        "FEISHU_APP_ID": "cli_test123",
        "FEISHU_APP_SECRET": "secret456",
        "FEISHU_MCP_TOKEN": "m-abc123",
        "FEISHU_USER_ACCESS_TOKEN": "",  # empty — should be excluded
    }
    with patch.dict(os.environ, env_override, clear=False):
        result = get_feishu_sandbox_env()

    assert result["FEISHU_APP_ID"] == "cli_test123"
    assert result["FEISHU_APP_SECRET"] == "secret456"
    assert result["FEISHU_MCP_TOKEN"] == "m-abc123"
    assert "FEISHU_USER_ACCESS_TOKEN" not in result


def test_get_feishu_sandbox_env_returns_empty_when_unset() -> None:
    keys = ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_MCP_TOKEN", "FEISHU_USER_ACCESS_TOKEN"]
    env_override = {k: "" for k in keys}
    with patch.dict(os.environ, env_override, clear=False):
        # Unset them explicitly
        for k in keys:
            os.environ.pop(k, None)
        result = get_feishu_sandbox_env()

    assert result == {}

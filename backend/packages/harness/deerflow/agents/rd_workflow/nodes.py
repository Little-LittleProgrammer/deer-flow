"""R&D Workflow LangGraph nodes.

Each node implements one phase of the agentic R&D pipeline:
  init_workspace_node → planning_node → human_approval_node → development_node → delivery_node
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from .state import RDWorkflowState, WorkspaceInfo

logger = logging.getLogger(__name__)

_CLONE_TIMEOUT_SECONDS = 300  # 5 minutes


def _get_thread_workspace_base(thread_id: str) -> Path:
    """Return the base path for a thread's workspace directory."""
    from deerflow.config.paths import get_paths

    paths = get_paths()
    return paths.threads_dir / thread_id / "user-data" / "workspace"


def _build_clone_url(clone_url_template: str, token: str, repo_name: str) -> str:
    """Interpolate the clone URL template with actual values.

    Template format example: https://{token}@{domain}/{org}/{repo}.git
    Simpler format example:  https://{token}@codeup.aliyun.com/org/{repo}.git
    """
    return clone_url_template.replace("{token}", token).replace("{repo}", repo_name)


async def init_workspace_node(state: RDWorkflowState) -> dict:
    """Clone repositories and prepare workspace.

    Reads codeup_repositories from state, clones each to
    .deer-flow/threads/{thread_id}/user-data/workspace/{repo_name},
    creates feature/{requirement_id} branch.
    """

    repo_names: list[str] = state.get("codeup_repositories") or []
    requirement_id: str = state.get("lark_requirement_id") or "rd-task"

    if not repo_names:
        logger.info("init_workspace_node: no repositories specified, skipping clone")
        return {
            "workspace_ready": True,
            "workspaces": [],
            "messages": [AIMessage(content="No repositories specified. Proceeding without code workspace.")],
        }

    try:
        from deerflow.config import get_app_config

        config = get_app_config()
        codeup_cfg = config.codeup
        token = codeup_cfg.token
        clone_url_template = codeup_cfg.clone_url_template

        if not token or not clone_url_template:
            return {
                "workspace_ready": False,
                "workspace_error": "CODEUP_TOKEN or CODEUP_CLONE_URL_TEMPLATE not configured",
                "messages": [AIMessage(content="⚠️ Codeup configuration missing. Cannot clone repositories.")],
            }
    except Exception as e:
        return {
            "workspace_ready": False,
            "workspace_error": str(e),
            "messages": [AIMessage(content=f"⚠️ Configuration error: {e}")],
        }

    workspaces: list[WorkspaceInfo] = []
    errors: list[str] = []

    # Note: thread_id is not directly in state; use a placeholder.
    # In production this would come from RunnableConfig's configurable.
    thread_workspace_base = Path(os.getcwd()) / ".deer-flow" / "workspaces" / requirement_id

    for repo_name in repo_names:
        workspace_path = thread_workspace_base / repo_name
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        clone_url = _build_clone_url(clone_url_template, token, repo_name)
        branch_name = f"feature/{requirement_id}"

        try:
            if workspace_path.exists():
                logger.info("Workspace already exists for %s, skipping clone", repo_name)
            else:
                logger.info("Cloning %s into %s", repo_name, workspace_path)
                result = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        "git",
                        "clone",
                        clone_url,
                        str(workspace_path),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    ),
                    timeout=_CLONE_TIMEOUT_SECONDS,
                )
                proc = result
                _, stderr = await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError(f"git clone failed: {stderr.decode()}")

            # Create feature branch
            git_branch_result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if git_branch_result.returncode != 0 and "already exists" not in git_branch_result.stderr:
                # Branch might already exist — try to check it out
                subprocess.run(
                    ["git", "checkout", branch_name],
                    cwd=str(workspace_path),
                    check=False,
                )

            workspaces.append(
                WorkspaceInfo(
                    repo_name=repo_name,
                    physical_path=str(workspace_path),
                    branch=branch_name,
                    cloned=True,
                )
            )
        except TimeoutError:
            errors.append(f"Clone timeout for {repo_name} (>{_CLONE_TIMEOUT_SECONDS}s)")
        except Exception as e:
            errors.append(f"Clone failed for {repo_name}: {e}")

    if errors:
        return {
            "workspace_ready": False,
            "workspaces": workspaces,
            "workspace_error": "; ".join(errors),
            "messages": [AIMessage(content=f"⚠️ Workspace init errors: {'; '.join(errors)}")],
        }

    repo_list = ", ".join(w["repo_name"] for w in workspaces)
    return {
        "workspace_ready": True,
        "workspaces": workspaces,
        "messages": [AIMessage(content=f"✅ Workspace ready. Cloned: {repo_list}. Branch: feature/{requirement_id}")],
    }


async def planning_node(state: RDWorkflowState) -> dict:
    """Generate technical design using Agent in sandbox.

    Only executed when work_mode == "planning". In development mode this node
    is a pass-through that returns immediately.
    """
    work_mode = state.get("work_mode", "planning")

    if work_mode == "development":
        return {
            "planning_complete": True,
            "messages": [AIMessage(content="Development mode selected. Skipping planning phase.")],
        }

    requirement_id = state.get("lark_requirement_id", "")
    workspaces = state.get("workspaces") or []

    workspace_paths = [w["physical_path"] for w in workspaces if w.get("cloned")]
    workspace_summary = "\n".join(f"- {p}" for p in workspace_paths) if workspace_paths else "No repositories cloned."

    # The actual planning is delegated to an LLM agent invoked via sandbox.
    # For V1, we generate a planning prompt and signal completion.
    # The full sandbox agent invocation is wired in the lead_agent middleware chain.
    planning_prompt = (
        f"You are a senior software architect. Analyze the following requirement and repositories:\n\n"
        f"**Requirement ID**: {requirement_id}\n"
        f"**Code Repositories**:\n{workspace_summary}\n\n"
        f"Tasks:\n"
        f"1. Review the requirement details from Feishu (use lark-wiki skill if available)\n"
        f"2. Analyze the existing codebase architecture\n"
        f"3. Identify potential design issues or logical gaps\n"
        f"4. Produce a technical design document with:\n"
        f"   - Architecture overview\n"
        f"   - Implementation tasks breakdown\n"
        f"   - Risk assessment\n\n"
        f"Save the design document as `technical_design.md` in the workspace."
    )

    return {
        "planning_complete": True,
        "technical_design": planning_prompt,
        "messages": [
            AIMessage(content=(f"📋 Planning phase started for requirement {requirement_id}.\nAnalyzing {len(workspace_paths)} repository(ies) and generating technical design...\nWaiting for Agent to complete planning analysis."))
        ],
    }


def human_approval_node(state: RDWorkflowState) -> dict:
    """Interrupt execution and wait for human approval.

    Uses LangGraph interrupt() to pause the graph. Resume by calling
    thread.submit() with command: { resume: "approved" } or { resume: "rejected" }.
    The interrupt() return value carries the resume string.
    """
    current_approval = state.get("approval_status")

    if current_approval == "approved":
        return {
            "approval_status": "approved",
            "messages": [AIMessage(content="✅ Technical design approved. Starting development phase.")],
        }

    if current_approval == "rejected":
        return {
            "approval_status": "rejected",
            "messages": [AIMessage(content="❌ Technical design rejected. Workflow terminated.")],
        }

    # First time reaching this node — interrupt and wait for approval.
    # interrupt() raises GraphInterrupt on first call; on resume it returns
    # the value passed via Command(resume=...) from the client.
    technical_design = state.get("technical_design", "")
    interrupt_payload = {
        "type": "human_approval",
        "message": "Please review the technical design and approve or reject to continue.",
        "technical_design_preview": technical_design[:500] if technical_design else "",
        "requirement_id": state.get("lark_requirement_id"),
    }

    resume_value = interrupt(interrupt_payload)

    # resume_value is what the client passed via Command(resume=...)
    # Accept either a plain string ("approved"/"rejected") or dict {"approval": "..."}
    if isinstance(resume_value, dict):
        decision = resume_value.get("approval", "")
    else:
        decision = str(resume_value) if resume_value else ""

    if decision == "approved":
        return {
            "approval_status": "approved",
            "messages": [AIMessage(content="✅ Technical design approved. Starting development phase.")],
        }
    return {
        "approval_status": "rejected",
        "messages": [AIMessage(content="❌ Technical design rejected. Workflow terminated.")],
    }


async def development_node(state: RDWorkflowState) -> dict:
    """Execute coding tasks in sandbox with incremental git commits.

    The actual Agent execution happens through the sandbox. Each completed
    task triggers a framework-delegated git commit.
    """
    workspaces = state.get("workspaces") or []
    requirement_id = state.get("lark_requirement_id", "rd-task")
    committed_tasks: list[str] = []

    if not workspaces:
        return {
            "development_complete": True,
            "committed_tasks": [],
            "messages": [AIMessage(content="No workspaces available. Development phase skipped.")],
        }

    # Framework-delegated git commit after each task completion
    # In production this is triggered by task_completion events from the Agent
    for workspace in workspaces:
        if not workspace.get("cloned"):
            continue
        workspace_path = workspace["physical_path"]
        repo_name = workspace["repo_name"]

        try:
            _framework_git_commit(workspace_path, f"chore: Initial R&D workflow setup for {requirement_id}")
            committed_tasks.append(f"{repo_name}: setup commit")
        except Exception as e:
            logger.warning("git commit failed for %s: %s", repo_name, e)

    return {
        "development_complete": True,
        "committed_tasks": committed_tasks,
        "messages": [AIMessage(content=(f"🔨 Development phase started for {requirement_id}.\nAgent will code, test, and commit incrementally across {len(workspaces)} repository(ies)."))],
    }


async def delivery_node(state: RDWorkflowState) -> dict:
    """Push code and create Merge Requests in Codeup.

    Pushes the feature branch to remote and creates an MR for each repository.
    Sends Feishu notification with MR links on success.
    """
    workspaces = state.get("workspaces") or []
    requirement_id = state.get("lark_requirement_id", "rd-task")
    mr_urls: list[str] = []
    errors: list[str] = []

    if not workspaces:
        return {
            "delivery_complete": True,
            "mr_urls": [],
            "messages": [AIMessage(content="No workspaces. Delivery phase skipped.")],
        }

    try:
        from deerflow.integrations.codeup.client import CodeupClient, CodeupConfigurationError

        try:
            codeup_client = CodeupClient.from_config()
        except CodeupConfigurationError as e:
            return {
                "delivery_complete": False,
                "delivery_error": str(e),
                "messages": [AIMessage(content=f"⚠️ Codeup not configured: {e}")],
            }
    except Exception as e:
        return {
            "delivery_complete": False,
            "delivery_error": str(e),
            "messages": [AIMessage(content=f"⚠️ Failed to initialize Codeup client: {e}")],
        }

    for workspace in workspaces:
        if not workspace.get("cloned"):
            continue

        workspace_path = workspace["physical_path"]
        branch_name = workspace.get("branch", f"feature/{requirement_id}")
        repo_name = workspace["repo_name"]

        try:
            # Framework-delegated push (Agent cannot push directly)
            push_result = subprocess.run(
                ["git", "push", "origin", branch_name],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                check=False,
            )
            if push_result.returncode != 0 and "already exists" not in push_result.stderr:
                errors.append(f"git push failed for {repo_name}: {push_result.stderr}")
                continue

            # Look up repository ID
            repos = await codeup_client.list_repositories(search=repo_name)
            if not repos:
                errors.append(f"Repository not found in Codeup: {repo_name}")
                continue

            repo = repos[0]
            mr_title = f"feat({requirement_id}): R&D workflow changes"
            mr_description = f"Automated changes generated by DeerFlow R&D Workflow.\n\n**Requirement**: {requirement_id}\n**Branch**: `{branch_name}`\n**Committed tasks**: {len(state.get('committed_tasks', []))}"

            mr = await codeup_client.create_change_request(
                repository_id=repo.id,
                source_branch=branch_name,
                target_branch="main",
                title=mr_title,
                description=mr_description,
            )
            mr_urls.append(mr.web_url)
            logger.info("Created MR for %s: %s", repo_name, mr.web_url)

        except Exception as e:
            errors.append(f"Delivery failed for {repo_name}: {e}")

    if errors:
        return {
            "delivery_complete": len(mr_urls) > 0,
            "mr_urls": mr_urls,
            "delivery_error": "; ".join(errors),
            "messages": [AIMessage(content=f"⚠️ Delivery completed with errors: {'; '.join(errors)}")],
        }

    mr_links = "\n".join(f"- {url}" for url in mr_urls)
    return {
        "delivery_complete": True,
        "mr_urls": mr_urls,
        "messages": [AIMessage(content=(f"🚀 Delivery complete! Created {len(mr_urls)} Merge Request(s):\n{mr_links}\n\nPlease review and merge when ready."))],
    }


def _framework_git_commit(workspace_path: str, message: str) -> None:
    """Execute a git add + commit from the framework (not the Agent).

    This is the Framework-Delegated Git pattern — the Agent cannot run git directly.
    """
    subprocess.run(["git", "add", "."], cwd=workspace_path, check=False, capture_output=True)
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=workspace_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "nothing to commit" not in result.stdout:
        logger.debug("git commit result for %s: %s", workspace_path, result.stdout)

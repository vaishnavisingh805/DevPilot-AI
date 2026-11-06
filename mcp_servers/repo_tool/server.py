"""MCP Repository Isolation Tool Server.

Provides sandboxed, isolated repository operations ensuring the main
repository cannot be altered without strict human approval.
"""

import difflib
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from mcp.server.fastmcp import FastMCP
from config.settings import settings
from core.git.git_manager import git_manager, validate_github_url
from core.rag.vector_store import vector_store

# Initialize FastMCP Server
repo_mcp = FastMCP("mcp-repository-tool")


def _resolve_sandbox_path(run_id: str) -> Path:
    """Validate and resolve sandbox run path preventing path traversal."""
    sandbox_base = settings.SANDBOX_ROOT / "runs"
    sandbox_dir = (sandbox_base / run_id).resolve()
    # Ensure sandbox_dir is within sandbox_base
    if not str(sandbox_dir).startswith(str(sandbox_base.resolve())):
        raise PermissionError(f"Access denied: Path traversal attempted for run_id '{run_id}'")
    return sandbox_dir


@repo_mcp.tool()
def create_isolated_sandbox(source_repo_rel_path: str = "sample_repo") -> Dict[str, Any]:
    """Creates a temporary, isolated sandbox copy of the target repository for safe agent edits.

    Args:
        source_repo_rel_path: Path to source repository relative to SANDBOX_ROOT.

    Returns:
        Dictionary containing run_id and absolute sandbox_path.
    """
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    source_path = (settings.SANDBOX_ROOT / source_repo_rel_path).resolve()

    if not source_path.exists():
        return {
            "success": False,
            "error": f"Source repository '{source_path}' does not exist.",
        }

    target_sandbox = _resolve_sandbox_path(run_id)
    target_sandbox.parent.mkdir(parents=True, exist_ok=True)

    # Copy files while ignoring caches
    shutil.copytree(
        source_path,
        target_sandbox,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".git"),
    )

    return {
        "success": True,
        "run_id": run_id,
        "sandbox_path": str(target_sandbox),
        "source_repo": str(source_path),
        "message": f"Isolated sandbox created successfully at {target_sandbox}",
    }


@repo_mcp.tool()
def read_file_from_sandbox(run_id: str, file_rel_path: str) -> Dict[str, Any]:
    """Safely reads the contents of a file inside an isolated sandbox.

    Args:
        run_id: The ID of the isolated sandbox run.
        file_rel_path: File path relative to the sandbox root.

    Returns:
        Dictionary with file content or error.
    """
    sandbox_dir = _resolve_sandbox_path(run_id)
    target_file = (sandbox_dir / file_rel_path).resolve()

    if not str(target_file).startswith(str(sandbox_dir)):
        return {
            "success": False,
            "error": "Path traversal detected: attempted to read outside sandbox.",
        }

    if not target_file.exists():
        return {
            "success": False,
            "error": f"File '{file_rel_path}' does not exist in sandbox.",
        }

    try:
        content = target_file.read_text(encoding="utf-8")
        return {
            "success": True,
            "file_path": file_rel_path,
            "content": content,
            "line_count": len(content.splitlines()),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@repo_mcp.tool()
def list_sandbox_files(run_id: str) -> Dict[str, Any]:
    """Lists all non-ignored source and configuration files in the isolated sandbox.

    Args:
        run_id: The ID of the isolated sandbox run.

    Returns:
        Dictionary containing list of relative file paths in POSIX format.
    """
    try:
        sandbox_dir = _resolve_sandbox_path(run_id)
    except Exception as e:
        return {"success": False, "error": str(e), "files": []}

    if not sandbox_dir.exists():
        return {"success": False, "error": f"Sandbox '{run_id}' does not exist.", "files": []}

    ignored_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
    files_list = []
    for root, dirs, files in os.walk(sandbox_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.endswith(".egg-info")]
        for f in files:
            full_path = Path(root) / f
            try:
                rel_p = str(full_path.relative_to(sandbox_dir)).replace("\\", "/")
                files_list.append(rel_p)
            except ValueError:
                continue

    return {
        "success": True,
        "run_id": run_id,
        "total_files": len(files_list),
        "files": sorted(files_list),
    }


@repo_mcp.tool()
def apply_patch_to_sandbox(
    run_id: str,
    file_rel_path: str,
    new_content: str,
    justification: str = "Agent modification",
) -> Dict[str, Any]:
    """Applies modified code content to a file inside the isolated sandbox.

    Args:
        run_id: The sandbox run ID.
        file_rel_path: Target file path relative to sandbox.
        new_content: Full proposed code content.
        justification: Reasoning for this code update.

    Returns:
        Dictionary containing diff, status, and affected file path.
    """
    sandbox_dir = _resolve_sandbox_path(run_id)
    target_file = (sandbox_dir / file_rel_path).resolve()

    if not str(target_file).startswith(str(sandbox_dir)):
        return {
            "success": False,
            "error": "Security Alert: Cannot write outside designated sandbox.",
        }

    original_content = ""
    is_new_file = not target_file.exists()

    if not is_new_file:
        try:
            original_content = target_file.read_text(encoding="utf-8")
        except Exception:
            original_content = ""

    # Ensure parent directory exists
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(new_content, encoding="utf-8")

    # Generate unified diff
    orig_lines = original_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            orig_lines,
            new_lines,
            fromfile=f"a/{file_rel_path}",
            tofile=f"b/{file_rel_path}",
        )
    )

    if not is_new_file and not diff.strip():
        return {
            "success": False,
            "error": f"Empty patch: Proposed content for '{file_rel_path}' is identical to existing content in sandbox.",
            "file_path": file_rel_path,
            "diff": "",
        }

    return {
        "success": True,
        "file_path": file_rel_path,
        "is_new_file": is_new_file,
        "diff": diff,
        "justification": justification,
        "message": f"Successfully updated '{file_rel_path}' in sandbox {run_id}",
    }


@repo_mcp.tool()
def commit_sandbox_to_main(
    run_id: str,
    target_repo_rel_path: str = "sample_repo",
    human_approved: bool = False,
    approval_notes: str = "",
) -> Dict[str, Any]:
    """Commits validated changes from sandbox to main repo. Strictly requires human approval.

    Args:
        run_id: The sandbox run ID.
        target_repo_rel_path: Destination repo relative to SANDBOX_ROOT.
        human_approved: Boolean gatekeeper flag indicating explicit human sign-off.
        approval_notes: Justification or approval sign-off note.

    Returns:
        Status dictionary confirming commit or rejecting if approval is missing.
    """
    if not human_approved:
        return {
            "success": False,
            "error": "HUMAN_APPROVAL_REQUIRED: Code changes cannot be applied to main branch without explicit human sign-off.",
            "status": "BLOCKED",
        }

    sandbox_dir = _resolve_sandbox_path(run_id)
    if not sandbox_dir.exists():
        return {"success": False, "error": f"Sandbox '{run_id}' does not exist."}

    # For Git repositories (remote GitHub clones or local Git workspaces):
    # Changes are committed strictly inside the local isolated branch.
    # The remote default branch and remote repository are NEVER modified or pushed to.
    if target_repo_rel_path.startswith("https://") or (sandbox_dir / ".git").exists():
        status_res = git_manager.get_git_status(sandbox_dir)
        if status_res.get("is_dirty"):
            git_manager.stage_file(sandbox_dir, ".")
            commit_res = git_manager.commit_changes(
                sandbox_dir,
                f"feat(autonomous): approved changes ({approval_notes[:60]})",
            )
            return {
                "success": True,
                "status": "COMMITTED_LOCALLY",
                "message": "Candidate changes safely committed to local isolated branch. Remote default branch preserved untouched.",
                "approval_notes": approval_notes,
                "commit_sha": commit_res.get("commit_sha"),
            }

        # Check if changes were already committed on isolated branch
        diff_res = git_manager.get_git_diff(sandbox_dir, base_branch="main")
        if not diff_res.get("has_diff"):
            diff_res = git_manager.get_git_diff(sandbox_dir)

        if diff_res.get("has_diff"):
            return {
                "success": True,
                "status": "COMMITTED_LOCALLY",
                "message": "Candidate changes safely verified on local isolated branch. Remote default branch preserved untouched.",
                "approval_notes": approval_notes,
                "commit_sha": git_manager.get_head_commit_sha(sandbox_dir),
            }

        return {
            "success": False,
            "error": "No modified files or commits found in isolated branch to commit.",
            "status": "EMPTY_BRANCH",
        }

    main_repo = (settings.SANDBOX_ROOT / target_repo_rel_path).resolve()

    # Copy files over
    for root, dirs, files in os.walk(sandbox_dir):
        rel_root = os.path.relpath(root, sandbox_dir)
        dest_root = main_repo / rel_root
        dest_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            src_file = Path(root) / f
            dest_file = dest_root / f
            shutil.copy2(src_file, dest_file)

    return {
        "success": True,
        "status": "COMMITTED",
        "message": f"Sandbox changes committed to '{target_repo_rel_path}' with verified human approval.",
        "approval_notes": approval_notes,
    }


@repo_mcp.tool()
def clone_github_repository(
    repo_url: str,
    base_branch: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Clones a GitHub repository into an isolated sandbox run directory."""
    r_id = run_id or f"run_git_{uuid.uuid4().hex[:8]}"
    sandbox_dir = _resolve_sandbox_path(r_id)

    res = git_manager.clone_repository(
        repo_url=repo_url,
        target_dir=sandbox_dir,
        base_branch=base_branch,
    )
    if res.get("success"):
        res["run_id"] = r_id
        res["sandbox_path"] = str(sandbox_dir)
    return res


@repo_mcp.tool()
def create_git_branch(run_id: str, task_id: str) -> Dict[str, Any]:
    """Creates and checks out an isolated agentic branch agentic/{task_id}-{run_id}."""
    sandbox_dir = _resolve_sandbox_path(run_id)
    if not sandbox_dir.exists():
        return {"success": False, "error": f"Sandbox '{run_id}' does not exist."}
    return git_manager.create_isolated_branch(repo_dir=sandbox_dir, task_id=task_id, run_id=run_id)


@repo_mcp.tool()
def get_git_status(run_id: str) -> Dict[str, Any]:
    """Returns structured status of working tree (added, modified, deleted, untracked)."""
    sandbox_dir = _resolve_sandbox_path(run_id)
    if not sandbox_dir.exists():
        return {"success": False, "error": f"Sandbox '{run_id}' does not exist."}
    return git_manager.get_git_status(repo_dir=sandbox_dir)


@repo_mcp.tool()
def get_git_diff(
    run_id: str,
    staged: bool = False,
    base_branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Returns real git diff of changes inside sandbox."""
    sandbox_dir = _resolve_sandbox_path(run_id)
    if not sandbox_dir.exists():
        return {"success": False, "error": f"Sandbox '{run_id}' does not exist."}
    return git_manager.get_git_diff(repo_dir=sandbox_dir, staged=staged, base_branch=base_branch)


@repo_mcp.tool()
def index_repository_rag(run_id: str, repo_id: Optional[str] = None) -> Dict[str, Any]:
    """Extracts AST code chunks and indexes them into ChromaDB vector store."""
    sandbox_dir = _resolve_sandbox_path(run_id)
    if not sandbox_dir.exists():
        return {"success": False, "error": f"Sandbox '{run_id}' does not exist."}
    return vector_store.index_repository(repo_root=sandbox_dir, repo_id=repo_id or run_id)


@repo_mcp.tool()
def query_repository_rag(
    query: str,
    run_id: Optional[str] = None,
    repo_id: Optional[str] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """Performs semantic code search over indexed repository chunks."""
    target_repo = repo_id or run_id or "default_repo"
    chunks = vector_store.query_codebase(query=query, repo_id=target_repo, top_k=top_k)
    return {
        "success": True,
        "query": query,
        "repo_id": target_repo,
        "chunk_count": len(chunks),
        "results": chunks,
    }


@repo_mcp.tool()
def publish_github_pull_request(
    run_id: str,
    repo_url: str,
    base_branch: str = "main",
    task_id: str = "TASK-01",
    requirement_prompt: str = "",
    auth_token: Optional[str] = None,
    approver: str = "Lead Engineer",
    approval_notes: str = "Approved for publication",
) -> Dict[str, Any]:
    """Publishes the approved isolated branch to GitHub as a Pull Request after HITL verification."""
    from core.github.pr_publisher import pr_publisher
    sandbox_dir = _resolve_sandbox_path(run_id)
    return pr_publisher.publish_pull_request(
        run_id=run_id,
        sandbox_path=sandbox_dir,
        repo_url=repo_url,
        base_branch=base_branch,
        task_id=task_id,
        requirement_prompt=requirement_prompt,
        auth_token=auth_token,
        approver=approver,
        approval_notes=approval_notes,
    )


if __name__ == "__main__":
    repo_mcp.run()


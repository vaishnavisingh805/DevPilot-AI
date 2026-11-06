"""Python Client interface for MCP Repository Isolation Tool."""

from typing import Dict, Any, Optional
from mcp_servers.repo_tool.server import (
    create_isolated_sandbox,
    read_file_from_sandbox,
    list_sandbox_files,
    apply_patch_to_sandbox,
    commit_sandbox_to_main,
    clone_github_repository,
    create_git_branch,
    get_git_status,
    get_git_diff,
    index_repository_rag,
    query_repository_rag,
    publish_github_pull_request,
)


class MCPRepoClient:
    """Client wrapper for the MCP Repository Isolation Tool."""

    def __init__(self):
        self.name = "mcp-repo-client"

    def create_sandbox(self, source_repo: str = "sample_repo") -> Dict[str, Any]:
        return create_isolated_sandbox(source_repo)

    def read_file(self, run_id: str, file_path: str) -> Dict[str, Any]:
        return read_file_from_sandbox(run_id, file_path)

    def list_files(self, run_id: str) -> Dict[str, Any]:
        return list_sandbox_files(run_id)

    def apply_patch(
        self,
        run_id: str,
        file_path: str,
        content: str,
        justification: str = "Agent modification",
    ) -> Dict[str, Any]:
        return apply_patch_to_sandbox(run_id, file_path, content, justification)

    def commit_to_main(
        self,
        run_id: str,
        target_repo: str = "sample_repo",
        human_approved: bool = False,
        approval_notes: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        dest_repo = kwargs.get("target_repo_rel_path", target_repo)
        return commit_sandbox_to_main(
            run_id=run_id,
            target_repo_rel_path=dest_repo,
            human_approved=human_approved,
            approval_notes=approval_notes,
        )

    def clone_repository(
        self,
        repo_url: str,
        base_branch: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return clone_github_repository(
            repo_url=repo_url,
            base_branch=base_branch,
            run_id=run_id,
        )

    def create_branch(self, run_id: str, task_id: str) -> Dict[str, Any]:
        return create_git_branch(run_id=run_id, task_id=task_id)

    def get_status(self, run_id: str) -> Dict[str, Any]:
        return get_git_status(run_id=run_id)

    def get_diff(
        self,
        run_id: str,
        staged: bool = False,
        base_branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        return get_git_diff(run_id=run_id, staged=staged, base_branch=base_branch)

    def index_rag(self, run_id: str, repo_id: Optional[str] = None) -> Dict[str, Any]:
        return index_repository_rag(run_id=run_id, repo_id=repo_id)

    def query_rag(
        self,
        query: str,
        run_id: Optional[str] = None,
        repo_id: Optional[str] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        return query_repository_rag(
            query=query,
            run_id=run_id,
            repo_id=repo_id,
            top_k=top_k,
        )

    def publish_pull_request(
        self,
        run_id: str,
        repo_url: str,
        base_branch: str = "main",
        task_id: str = "TASK-01",
        requirement_prompt: str = "",
        auth_token: Optional[str] = None,
        approver: str = "Lead Engineer",
        approval_notes: str = "Approved for publication",
    ) -> Dict[str, Any]:
        return publish_github_pull_request(
            run_id=run_id,
            repo_url=repo_url,
            base_branch=base_branch,
            task_id=task_id,
            requirement_prompt=requirement_prompt,
            auth_token=auth_token,
            approver=approver,
            approval_notes=approval_notes,
        )


# Global client instance
mcp_repo_client = MCPRepoClient()



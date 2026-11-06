"""Pydantic schemas for Repository Configuration and Git Targets."""

from typing import Optional
from pydantic import BaseModel, Field, field_validator
from core.git.git_manager import validate_github_url


class RepositoryConfig(BaseModel):
    """Configuration model for a target repository and branch."""

    repo_url: Optional[str] = Field(
        default="sample_repo",
        description="GitHub HTTPS URL or local path relative to SANDBOX_ROOT",
    )
    base_branch: Optional[str] = Field(default="main", description="Target base branch")
    task_id: str = Field(default="TASK-01", description="Identifier for task/issue")
    is_github: bool = Field(default=False, description="True if URL is a remote GitHub repository")
    auth_token: Optional[str] = Field(default=None, description="Optional GitHub Personal Access Token (masked)")

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return "sample_repo"
        v_str = str(v).strip()
        if v_str.startswith("https://"):
            is_valid, norm = validate_github_url(v_str)
            if not is_valid:
                raise ValueError(norm)
            return norm
        return v_str

    def model_post_init(self, __context) -> None:
        if self.repo_url and self.repo_url.startswith("https://"):
            self.is_github = True


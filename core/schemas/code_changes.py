"""Pydantic schemas for Code Changes, Diffs, and Patches."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    MODIFY = "modify"
    CREATE = "create"
    DELETE = "delete"


class FilePatch(BaseModel):
    """Represents a change proposal to an individual file."""
    file_path: str = Field(..., description="Target file path relative to repo root")
    change_type: ChangeType = Field(default=ChangeType.MODIFY)
    original_content: Optional[str] = Field(default=None, description="Original content if existing")
    modified_content: str = Field(..., description="Proposed new complete content")
    unified_diff: str = Field(default="", description="Unified diff formatted patch")
    affected_symbols: List[str] = Field(
        default_factory=list,
        description="Function or class symbols modified or introduced"
    )
    justification: str = Field(..., description="Why this code change is necessary to meet requirements")


class CodeChangeProposal(BaseModel):
    """Collection of file patches representing an atomic change set."""
    proposal_id: str = Field(default_factory=lambda: f"CCP-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    task_id: str
    author_agent: str = Field(..., description="e.g. Google-ADK-CoderAgent")
    framework: str = Field(default="google_adk")
    patches: List[FilePatch] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_validated_by_tests: bool = False
    is_approved_by_human: bool = False
    approval_notes: Optional[str] = None


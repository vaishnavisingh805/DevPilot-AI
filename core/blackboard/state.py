"""Blackboard State Model."""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from core.schemas import (
    DeveloperRequirement,
    RequirementAnalysis,
    ExecutionPlan,
    CodeChangeProposal,
    FilePatch,
    TestResultReport,
    SecurityAuditReport,
    ProvenanceRecord,
    FinalDeliveryPackage,
)


class BlackboardState(BaseModel):
    """The central state of the Shared Blackboard."""
    version: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Blackboard Knowledge Domains
    requirement: Optional[DeveloperRequirement] = None
    analysis: Optional[RequirementAnalysis] = None
    plan: Optional[ExecutionPlan] = None
    working_proposals: List[CodeChangeProposal] = Field(default_factory=list)
    active_patches: Dict[str, FilePatch] = Field(default_factory=dict)
    test_reports: List[TestResultReport] = Field(default_factory=list)
    security_audit: Optional[SecurityAuditReport] = None
    provenance_records: List[ProvenanceRecord] = Field(default_factory=list)
    human_approval_status: str = Field(
        default="pending",
        description="'pending', 'approved', 'rejected'"
    )
    human_approval_notes: Optional[str] = None
    failure_recovery_cycles: int = 0
    final_delivery: Optional[FinalDeliveryPackage] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


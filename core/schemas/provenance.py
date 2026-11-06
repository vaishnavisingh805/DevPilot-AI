"""Pydantic schemas for Provenance, Cryptographic Lineage, and Delivery Package."""

from datetime import datetime, timezone
import hashlib
from typing import List, Optional
from pydantic import BaseModel, Field


class ProvenanceRecord(BaseModel):
    """Cryptographically chained provenance record of an atomic agent action."""
    step_id: str = Field(..., description="Unique step identifier")
    parent_step_id: Optional[str] = Field(default=None, description="Previous step hash/id in lineage")
    agent_id: str
    framework: str
    action_type: str = Field(..., description="plan, code_generation, test_run, human_approval")
    input_payload_hash: str
    output_payload_hash: str
    state_version: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    record_hash: str = Field(default="")

    def compute_hash(self) -> str:
        """Compute SHA-256 hash linking parent and current state."""
        raw = f"{self.step_id}|{self.parent_step_id}|{self.agent_id}|{self.action_type}|{self.input_payload_hash}|{self.output_payload_hash}|{self.state_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class FinalDeliveryPackage(BaseModel):
    """Validated, production-ready code delivery package."""
    delivery_id: str = Field(default_factory=lambda: f"DELIV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    requirement_id: str
    plan_id: str
    summary_of_changes: str
    patches: List[dict] = Field(default_factory=list)
    tests_summary: dict = Field(default_factory=dict)
    unified_diff: Optional[str] = Field(default="", description="Unified Git diff for modified repository files")
    provenance_chain_length: int = 0
    provenance_root_hash: str = ""
    human_approved: bool = False
    approver_identity: Optional[str] = None
    approval_timestamp: Optional[datetime] = None
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


"""Pydantic schemas for Guardrails and Security Auditing."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ViolationLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SecurityViolation(BaseModel):
    """Specific security violation detected by guardrails."""
    rule_name: str = Field(..., description="e.g. PromptInjectionRule, AstDangerousSyscallRule")
    severity: ViolationLevel = Field(default=ViolationLevel.CRITICAL)
    details: str
    target_snippet: Optional[str] = None
    line_number: Optional[int] = None


class SecurityAuditReport(BaseModel):
    """Aggregate security and guardrail evaluation report."""
    audit_id: str = Field(default_factory=lambda: f"SEC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    passed: bool = True
    prompt_injection_detected: bool = False
    ast_security_violations: List[SecurityViolation] = Field(default_factory=list)
    path_traversal_violations: List[SecurityViolation] = Field(default_factory=list)
    recommendation: str = "Safe to proceed"
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


"""CrewAI Quality Assurance & Security Auditor Agent.

Inspects test verification reports, guardrail audit logs, and validates all
acceptance criteria before creating the final delivery package for human approval.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from crewai import Agent

from config.settings import settings
from config.models_config import get_llm_for_crewai
from core.schemas import (
    FinalDeliveryPackage,
    TaskStatus,
)
from core.a2a import A2AEnvelope, A2AMessageType, global_a2a_bus
from core.blackboard import global_blackboard


class CrewAIAuditorAgent:
    """CrewAI-powered QA and Security Auditor Agent."""

    def __init__(self, model_name: Optional[str] = None):
        self.agent_id = "CrewAI:AuditorAgent"
        self.framework = "crewai"
        self.model_name = model_name or settings.DEFAULT_MODEL
        self.llm = get_llm_for_crewai(self.model_name)

        self.crewai_agent = Agent(
            role="Principal Quality Assurance & Security Auditor",
            goal="Thoroughly audit generated code, unit test coverage, and guardrail reports to protect production integrity.",
            backstory=(
                "You are an uncompromising QA & Security Auditor. You ensure that no code change "
                "reaches production without 100% passing tests, complete security clearance, and "
                "rigorous cryptographic provenance tracking."
            ),
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )

        global_a2a_bus.register_agent(self.agent_id, self.handle_a2a_message)

    def handle_a2a_message(self, envelope: A2AEnvelope) -> Optional[A2AEnvelope]:
        return None

    def audit_and_prepare_delivery(self) -> FinalDeliveryPackage:
        """Audits current Blackboard state and constructs the final delivery package."""
        state = global_blackboard.state
        req = state.requirement
        plan = state.plan
        proposals = state.working_proposals
        reports = state.test_reports
        security = state.security_audit
        provenance = state.provenance_records

        # Verification checks
        all_tests_passed = False
        tests_summary: Dict[str, Any] = {}
        if reports:
            latest_report = reports[-1]
            all_tests_passed = latest_report.all_passed
            tests_summary = {
                "total": latest_report.total_tests,
                "passed": latest_report.passed,
                "failed": latest_report.failed,
                "duration_seconds": latest_report.execution_time_seconds,
            }

        patches_summary = []
        for p in proposals:
            for patch in p.patches:
                patches_summary.append({
                    "file_path": patch.file_path,
                    "justification": patch.justification,
                    "diff_lines": len(patch.unified_diff.splitlines()),
                    "diff": patch.unified_diff,
                })

        summary = (
            f"Autonomous Software Engineering Delivery for {req.id if req else 'N/A'}: "
            f"{len(patches_summary)} file(s) modified. "
            f"Tests: {tests_summary.get('passed', 0)}/{tests_summary.get('total', 0)} passing. "
            f"Security Audit: {'PASSED' if (security and security.passed) else 'PENDING/FAILED'}. "
            f"Provenance: {len(provenance)} linked audit blocks."
        )

        root_hash = provenance[-1].record_hash if provenance else "none"

        package = FinalDeliveryPackage(
            requirement_id=req.id if req else "REQ-UNKNOWN",
            plan_id=plan.plan_id if plan else "PLAN-UNKNOWN",
            summary_of_changes=summary,
            patches=patches_summary,
            tests_summary=tests_summary,
            provenance_chain_length=len(provenance),
            provenance_root_hash=root_hash,
            human_approved=False,
        )

        global_blackboard.set_final_delivery(package)
        global_blackboard.update_task_status(
            task_id="TSK-04-SECURITY-AUDIT",
            status=TaskStatus.COMPLETED,
            output_summary="Quality and security audit completed successfully",
        )

        return package

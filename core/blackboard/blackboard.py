"""Shared Blackboard Engine with visible state updates and observer notifications."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Dict, Any

from config.settings import settings
from core.blackboard.state import BlackboardState
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


class BlackboardEvent:
    """Event emitted whenever the Blackboard state is modified."""
    def __init__(
        self,
        event_type: str,
        section: str,
        state_version: int,
        details: str,
        data: Optional[Dict[str, Any]] = None,
    ):
        self.event_type = event_type
        self.section = section
        self.state_version = state_version
        self.details = details
        self.data = data or {}
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "section": self.section,
            "state_version": self.state_version,
            "details": self.details,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


class SharedBlackboard:
    """Thread-safe Shared Blackboard implementing visible state updates and subscriptions."""

    def __init__(self, persist_path: Optional[Path] = None):
        self._lock = threading.RLock()
        self._state = BlackboardState()
        self._subscribers: List[Callable[[BlackboardEvent], None]] = []
        self._event_log: List[BlackboardEvent] = []
        self.persist_path = persist_path or settings.BLACKBOARD_PERSIST_PATH

    @property
    def state(self) -> BlackboardState:
        """Read-only view of current state."""
        with self._lock:
            return self._state.model_copy(deep=True)

    @property
    def version(self) -> int:
        with self._lock:
            return self._state.version

    def get_event_history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._event_log]

    def subscribe(self, callback: Callable[[BlackboardEvent], None]) -> None:
        """Subscribe to visible state updates."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[BlackboardEvent], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _notify(self, event: BlackboardEvent) -> None:
        self._event_log.append(event)
        self._save_to_disk()
        for subscriber in list(self._subscribers):
            try:
                subscriber(event)
            except Exception as e:
                # Observers must not crash the blackboard
                print(f"[Blackboard Observer Error]: {e}")

    def _save_to_disk(self) -> None:
        try:
            if self.persist_path:
                self.persist_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.persist_path, "w", encoding="utf-8") as f:
                    f.write(self._state.model_dump_json(indent=2))
        except Exception as e:
            print(f"[Blackboard Persistence Warning]: {e}")

    def reset(self) -> None:
        """Reset the blackboard to clean initial state."""
        with self._lock:
            self._state = BlackboardState()
            self._event_log.clear()
            event = BlackboardEvent(
                event_type="STATE_RESET",
                section="all",
                state_version=self._state.version,
                details="Blackboard state has been reset",
            )
            self._notify(event)

    # --- Domain Specific State Update Methods ---

    def post_requirement(self, requirement: DeveloperRequirement) -> None:
        with self._lock:
            self._state.version += 1
            self._state.requirement = requirement
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="REQUIREMENT_POSTED",
                section="requirement",
                state_version=self._state.version,
                details=f"Requirement {requirement.id} posted",
                data={"id": requirement.id, "prompt": requirement.raw_prompt},
            )
            self._notify(event)

    def post_analysis(self, analysis: RequirementAnalysis) -> None:
        with self._lock:
            self._state.version += 1
            self._state.analysis = analysis
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="ANALYSIS_POSTED",
                section="analysis",
                state_version=self._state.version,
                details=f"Analysis posted: {analysis.title}",
                data={"title": analysis.title, "ac_count": len(analysis.acceptance_criteria)},
            )
            self._notify(event)

    def post_plan(self, plan: ExecutionPlan) -> None:
        with self._lock:
            self._state.version += 1
            self._state.plan = plan
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="PLAN_POSTED",
                section="plan",
                state_version=self._state.version,
                details=f"Execution plan {plan.plan_id} posted with {len(plan.tasks)} tasks",
                data={"plan_id": plan.plan_id, "task_count": len(plan.tasks)},
            )
            self._notify(event)

    def update_task_status(
        self,
        task_id: str,
        status: Any,
        output_summary: Optional[str] = None
    ) -> None:
        with self._lock:
            if not self._state.plan:
                return
            for task in self._state.plan.tasks:
                if task.id == task_id:
                    task.status = status
                    if output_summary:
                        task.output_summary = output_summary
                    if status == "in_progress" and not task.started_at:
                        task.started_at = datetime.now(timezone.utc)
                    elif status in ("completed", "failed"):
                        task.completed_at = datetime.now(timezone.utc)
                    self._state.version += 1
                    self._state.updated_at = datetime.now(timezone.utc)
                    event = BlackboardEvent(
                        event_type="TASK_STATUS_UPDATED",
                        section="plan",
                        state_version=self._state.version,
                        details=f"Task {task_id} updated to {status}",
                        data={"task_id": task_id, "status": str(status)},
                    )
                    self._notify(event)
                    break

    def post_code_proposal(self, proposal: CodeChangeProposal) -> None:
        with self._lock:
            self._state.version += 1
            self._state.working_proposals.append(proposal)
            for patch in proposal.patches:
                self._state.active_patches[patch.file_path] = patch
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="CODE_PROPOSAL_POSTED",
                section="working_patches",
                state_version=self._state.version,
                details=f"Code proposal {proposal.proposal_id} added ({len(proposal.patches)} patches)",
                data={"proposal_id": proposal.proposal_id, "author": proposal.author_agent},
            )
            self._notify(event)

    def post_test_report(self, report: TestResultReport) -> None:
        with self._lock:
            self._state.version += 1
            self._state.test_reports.append(report)
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="TEST_REPORT_POSTED",
                section="test_reports",
                state_version=self._state.version,
                details=f"Test run completed: {report.passed}/{report.total_tests} passed (All passed: {report.all_passed})",
                data={"passed": report.passed, "total": report.total_tests, "all_passed": report.all_passed},
            )
            self._notify(event)

    def post_security_audit(self, audit: SecurityAuditReport) -> None:
        with self._lock:
            self._state.version += 1
            self._state.security_audit = audit
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="SECURITY_AUDIT_POSTED",
                section="security_audit",
                state_version=self._state.version,
                details=f"Security audit complete: passed={audit.passed}",
                data={"passed": audit.passed, "violations": len(audit.ast_security_violations)},
            )
            self._notify(event)

    def post_provenance_record(self, record: ProvenanceRecord) -> None:
        with self._lock:
            self._state.version += 1
            self._state.provenance_records.append(record)
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="PROVENANCE_RECORDED",
                section="provenance",
                state_version=self._state.version,
                details=f"Provenance logged for step {record.step_id} by {record.agent_id}",
                data={"step_id": record.step_id, "hash": record.record_hash[:8]},
            )
            self._notify(event)

    def set_human_approval(self, status: str, notes: Optional[str] = None) -> None:
        with self._lock:
            self._state.version += 1
            self._state.human_approval_status = status
            self._state.human_approval_notes = notes
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="HUMAN_APPROVAL_UPDATED",
                section="human_approval",
                state_version=self._state.version,
                details=f"Human approval set to '{status}'",
                data={"status": status, "notes": notes},
            )
            self._notify(event)

    def increment_recovery_cycle(self) -> int:
        with self._lock:
            self._state.version += 1
            self._state.failure_recovery_cycles += 1
            if self._state.plan:
                self._state.plan.replan_count += 1
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="RECOVERY_CYCLE_INCREMENTED",
                section="failure_recovery",
                state_version=self._state.version,
                details=f"Entering failure recovery cycle #{self._state.failure_recovery_cycles}",
                data={"cycle": self._state.failure_recovery_cycles},
            )
            self._notify(event)
            return self._state.failure_recovery_cycles

    def set_final_delivery(self, package: FinalDeliveryPackage) -> None:
        with self._lock:
            self._state.version += 1
            self._state.final_delivery = package
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="FINAL_DELIVERY_PREPARED",
                section="final_delivery",
                state_version=self._state.version,
                details=f"Final delivery package {package.delivery_id} prepared",
                data={"delivery_id": package.delivery_id},
            )
            self._notify(event)

    def update_metadata(self, key: str, value: Any) -> None:
        with self._lock:
            self._state.version += 1
            self._state.metadata[key] = value
            self._state.updated_at = datetime.now(timezone.utc)
            event = BlackboardEvent(
                event_type="METADATA_UPDATED",
                section="metadata",
                state_version=self._state.version,
                details=f"Metadata '{key}' updated",
                data={"key": key},
            )
            self._notify(event)


# Global Blackboard singleton instance
global_blackboard = SharedBlackboard()


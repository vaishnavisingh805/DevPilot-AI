"""Failure-Driven Re-planning and Self-Healing Engine."""

from typing import Dict, Any, Optional
from core.blackboard import global_blackboard
from core.observability import callback_manager
from core.schemas import TaskStatus, TestResultReport
from agents.google_adk import GoogleADKDebuggerAgent
from agents.crewai import CrewAIPlannerAgent


class FailureRecoveryController:
    """Controls the self-healing feedback loop when tests or guardrails fail."""

    def __init__(self, max_recovery_cycles: int = 3):
        self.max_recovery_cycles = max_recovery_cycles
        self.debugger = GoogleADKDebuggerAgent()
        self.planner = CrewAIPlannerAgent()

    def attempt_recovery(
        self,
        run_id: str,
        sandbox_path: str,
        failed_report: TestResultReport,
    ) -> Dict[str, Any]:
        """Analyzes failure, triggers replanning, and applies debugger repair patch."""
        current_cycle = global_blackboard.state.failure_recovery_cycles
        if current_cycle >= self.max_recovery_cycles:
            callback_manager.on_agent_error(
                agent_id="FailureRecoveryController",
                framework="orchestration",
                error_message=f"Max recovery cycles ({self.max_recovery_cycles}) exceeded. Halting self-healing.",
            )
            return {
                "recovered": False,
                "cycles": current_cycle,
                "reason": f"Max recovery cycles ({self.max_recovery_cycles}) exceeded",
            }

        # 1. Collect failure diagnosis
        failure_reasons = []
        for item in failed_report.items:
            if item.outcome in ("failed", "error"):
                msg = item.failure_message or "Assertion failed"
                failure_reasons.append(f"{item.test_node_id}: {msg}")

        diag_text = "; ".join(failure_reasons) if failure_reasons else failed_report.raw_stdout[:300]

        callback_manager.on_agent_start(
            agent_id=self.debugger.agent_id,
            framework=self.debugger.framework,
            task_title=f"Self-Healing Debugging Cycle {current_cycle + 1}",
        )

        # 2. Trigger planner replan
        new_plan = self.planner.replan_on_failure(diag_text)

        # 3. Debugger synthesizes repair patch
        repair_proposal = self.debugger.diagnose_and_repair(
            run_id=run_id,
            task_id=f"TSK-RECOVERY-{current_cycle + 1}-DEBUG",
            failure_info=diag_text,
        )

        callback_manager.on_agent_finish(
            agent_id=self.debugger.agent_id,
            framework=self.debugger.framework,
            summary=f"Debugger applied corrective patch {repair_proposal.proposal_id}",
        )

        return {
            "recovered": True,
            "cycles": global_blackboard.state.failure_recovery_cycles,
            "repair_proposal_id": repair_proposal.proposal_id,
            "plan_id": new_plan.plan_id,
        }


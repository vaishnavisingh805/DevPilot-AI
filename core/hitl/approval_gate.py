"""Human-In-The-Loop (HITL) Gatekeeper Module."""

import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from config.settings import settings
from core.blackboard import global_blackboard
from core.observability import callback_manager
from core.guardrails.implementation_validator import implementation_validator
from mcp_servers.repo_tool import mcp_repo_client


class HITLGatekeeper:
    """Enforces compulsory human approval before any sandboxed code change is committed to the main codebase."""

    def __init__(self):
        self.require_approval = settings.REQUIRE_HUMAN_APPROVAL

    def compute_patch_hash(self, patches: Optional[Dict[str, Any]] = None) -> str:
        """Computes a deterministic SHA-256 hash over all active patches."""
        state_patches = patches if patches is not None else global_blackboard.state.active_patches
        if not state_patches:
            return ""

        hasher = hashlib.sha256()
        # Sort by file path for deterministic ordering
        for path in sorted(state_patches.keys()):
            patch = state_patches[path]
            c_type = getattr(patch, "change_type", "modify")
            c_type_val = c_type.value if hasattr(c_type, "value") else str(c_type)
            u_diff = getattr(patch, "unified_diff", "") or ""
            m_content = getattr(patch, "modified_content", "") or ""
            token = f"{path}:{c_type_val}:{u_diff.strip()}:{m_content.strip()}".encode("utf-8")
            hasher.update(token)
        return hasher.hexdigest()

    def evaluate_readiness(
        self,
        run_id: Optional[str] = None,
        target_repo: Optional[str] = None,
        expected_patch_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assesses whether all prerequisites (verified non-empty patches, tests passing,
        security audit clean, and context bindings) are satisfied before human sign-off."""
        state = global_blackboard.state
        rejection_reasons = []

        # 0. Simulation Mode & Local Demo Check
        is_local_demo = bool(
            state.metadata.get("is_local_demo")
            or (run_id and "local_demo" in str(run_id).lower())
            or (target_repo and "local_demo" in str(target_repo).lower())
        )
        if is_local_demo:
            rejection_reasons.append("HITL_APPROVAL_BLOCKED: Execution is marked as LOCAL DEMO — GENERATED WITHOUT LIVE AI AGENTS. Offline demonstrations cannot receive human sign-off or PR publishing.")

        is_simulated = bool(
            state.metadata.get("is_simulated")
            or settings.EXECUTION_MODE == "deterministic_simulation"
        )
        if is_simulated:
            rejection_reasons.append("HITL_APPROVAL_BLOCKED: Execution is marked as SIMULATED. Simulated changes cannot receive human sign-off.")

        # 1. Active patches validation
        patches = state.active_patches
        has_patches = len(patches) > 0
        if not has_patches:
            rejection_reasons.append("No active code patches recorded on blackboard.")
        else:
            empty_diffs = [
                p_path for p_path, p in patches.items()
                if not getattr(p, "unified_diff", "").strip() and not getattr(p, "modified_content", "").strip()
            ]
            if empty_diffs:
                has_patches = False
                rejection_reasons.append(f"Empty patch diffs detected for: {', '.join(empty_diffs)}")

            # Validate patch quality (reject comment-only or metadata-only patches)
            for p_path, patch_obj in patches.items():
                is_q_valid, q_msg = implementation_validator.validate_patch_quality(
                    file_path=patch_obj.file_path,
                    original_code=patch_obj.original_content or "",
                    modified_code=patch_obj.modified_content,
                    unified_diff=patch_obj.unified_diff,
                )
                if not is_q_valid:
                    has_patches = False
                    rejection_reasons.append(f"HITL_APPROVAL_BLOCKED: Patch quality violation for '{p_path}': {q_msg}")

            # Validate requirement alignment if requirement exists
            req_prompt = state.requirement.raw_prompt if state.requirement else ""
            if req_prompt and has_patches:
                is_aligned, align_rep = implementation_validator.validate_requirement_alignment(
                    requirement_prompt=req_prompt,
                    patches=patches,
                    acceptance_criteria=state.analysis.acceptance_criteria if state.analysis else None,
                )
                if not is_aligned:
                    for v in align_rep.get("violations", []):
                        rejection_reasons.append(f"HITL_APPROVAL_BLOCKED: {v}")

        # 2. Test reports validation
        has_reports = len(state.test_reports) > 0
        latest_test_passed = False
        if not has_reports:
            rejection_reasons.append("No test execution reports recorded on blackboard.")
        else:
            latest = state.test_reports[-1]
            if "FUNCTIONAL_TESTS_NOT_CONFIGURED" in getattr(latest, "raw_stderr", "") or "FUNCTIONAL_TESTS_NOT_CONFIGURED" in getattr(latest, "raw_stdout", ""):
                rejection_reasons.append("HITL_APPROVAL_BLOCKED: Functional tests are not configured in the target repository.")
            elif not latest.all_passed or latest.total_tests == 0 or latest.failed > 0:
                rejection_reasons.append(
                    f"Test suite verification failed: {latest.passed}/{latest.total_tests} passed, {latest.failed} failed."
                )
            else:
                latest_test_passed = True

        # 3. Security audit validation
        security_passed = False
        if not state.security_audit:
            rejection_reasons.append("No security audit report recorded on blackboard.")
        elif not state.security_audit.passed:
            rejection_reasons.append("Security audit failed with AST or guardrail violations.")
        else:
            security_passed = True

        # 4. Patch hash computation
        current_patch_hash = self.compute_patch_hash(patches)
        if not current_patch_hash and has_patches:
            rejection_reasons.append("Failed to compute valid cryptographic SHA-256 hash for active patches.")

        # 5. Context binding validation (if provided)
        bindings_valid = True
        repo_meta = state.metadata.get("repository", {})
        expected_sandbox_id = state.metadata.get("sandbox_run_id") or repo_meta.get("run_id")
        expected_repo_url = repo_meta.get("repo_url")

        if run_id and expected_sandbox_id and run_id != expected_sandbox_id and run_id != state.metadata.get("run_id"):
            bindings_valid = False
            rejection_reasons.append(f"Run ID mismatch: expected '{expected_sandbox_id}', received '{run_id}'.")

        if target_repo and expected_repo_url and target_repo != expected_repo_url and target_repo != "sample_repo":
            target_norm = target_repo.replace("\\", "/").rstrip("/").split("/")[-1]
            expected_norm = str(expected_repo_url).replace("\\", "/").rstrip("/").split("/")[-1]
            if target_norm != expected_norm:
                bindings_valid = False
                rejection_reasons.append(f"Repository mismatch: expected '{expected_repo_url}', received '{target_repo}'.")

        if expected_patch_hash and expected_patch_hash != current_patch_hash:
            bindings_valid = False
            rejection_reasons.append("Patch hash mismatch: Code was modified or tampered with after proposal.")

        can_approve = (
            not is_simulated
            and has_patches
            and latest_test_passed
            and security_passed
            and bindings_valid
            and bool(current_patch_hash)
            and len(rejection_reasons) == 0
        )

        return {
            "can_approve": can_approve,
            "has_patches": has_patches,
            "latest_test_passed": latest_test_passed,
            "security_passed": security_passed,
            "bindings_valid": bindings_valid,
            "patch_hash": current_patch_hash,
            "current_status": state.human_approval_status,
            "rejection_reasons": rejection_reasons,
        }

    def request_approval(self) -> None:
        """Flags that human intervention is now requested."""
        global_blackboard.set_human_approval("pending", "Awaiting human review")
        callback_manager.on_hitl_event("APPROVAL_REQUESTED", "Awaiting human sign-off on code changes")

    def approve_and_commit(
        self,
        run_id: str,
        approver: str = "Lead Engineer / Faculty Reviewer",
        notes: str = "Approved after reviewing diffs and passing test matrix",
        target_repo: str = "sample_repo",
        user: Optional[Any] = None,
        expected_patch_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Applies human approval and triggers MCP commit to main repository with RBAC and readiness validation."""
        # 1. RBAC check
        if user is not None:
            from core.auth import Permission
            if hasattr(user, "has_permission") and not user.has_permission(Permission.SIGN_OFF_HITL):
                return {
                    "success": False,
                    "error": f"AUTHORIZATION_DENIED: User '{getattr(user, 'user_id', 'unknown')}' lacks permission '{Permission.SIGN_OFF_HITL.value}'.",
                }

        # 2. Strict readiness evaluation
        readiness = self.evaluate_readiness(
            run_id=run_id,
            target_repo=target_repo,
            expected_patch_hash=expected_patch_hash,
        )
        if not readiness["can_approve"]:
            err_msg = f"HITL_APPROVAL_REJECTED: Preconditions failed: {'; '.join(readiness['rejection_reasons'])}"
            callback_manager.on_hitl_event("APPROVAL_REJECTED", err_msg)
            return {
                "success": False,
                "error": err_msg,
                "readiness": readiness,
            }

        # 3. Execute MCP commit to isolated branch FIRST (do not approve if commit fails)
        commit_res = mcp_repo_client.commit_to_main(
            run_id=run_id,
            target_repo=target_repo,
            human_approved=True,
            approval_notes=f"{approver}: {notes}",
        )
        if not commit_res.get("success"):
            err_msg = f"COMMIT_FAILED: {commit_res.get('error', 'Commit to sandbox branch failed.')}"
            return {
                "success": False,
                "error": err_msg,
                "commit_res": commit_res,
            }

        # 4. Seal approval contract
        patch_hash = readiness["patch_hash"]
        approval_contract = {
            "approved_by": approver,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "target_repo": target_repo,
            "patch_hash": patch_hash,
            "commit_sha": commit_res.get("commit_sha"),
            "notes": notes,
        }
        global_blackboard.update_metadata("approval_contract", approval_contract)

        # 5. Set human approval status on Blackboard
        global_blackboard.set_human_approval("approved", f"Approved by {approver}: {notes}")
        callback_manager.on_hitl_event("APPROVAL_GRANTED", f"Signed off by {approver}")

        # 6. Update final delivery package
        state = global_blackboard.state
        if state.final_delivery:
            state.final_delivery.human_approved = True
            state.final_delivery.approver_identity = approver
            state.final_delivery.approval_timestamp = datetime.now(timezone.utc)
            global_blackboard.set_final_delivery(state.final_delivery)

        return {
            "success": True,
            "message": commit_res.get("message", "Candidate changes verified, signed off, and committed."),
            "approval_contract": approval_contract,
            "commit_res": commit_res,
            "status": commit_res.get("status", "COMMITTED_LOCALLY"),
            "commit_sha": commit_res.get("commit_sha"),
        }

    def reject(
        self,
        reason: str = "Code changes did not meet requirements or quality standards",
    ) -> None:
        """Rejects code changes, blocking commit to main."""
        global_blackboard.set_human_approval("rejected", reason)
        callback_manager.on_hitl_event("APPROVAL_REJECTED", reason)


# Global HITL instance
hitl_gatekeeper = HITLGatekeeper()

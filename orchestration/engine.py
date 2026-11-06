"""Autonomous Software Engineering Orchestration Engine.

Coordinates the end-to-end multi-agent execution pipeline combining CrewAI,
Google ADK, Shared Blackboard, A2A Protocol, MCP Tools, and Guardrails.
"""

import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Union, Tuple, List

from config.settings import settings
from config.models_config import calculate_cost
from core.schemas import (
    DeveloperRequirement,
    RepositoryConfig,
    ExecutionPlan,
    CodeChangeProposal,
    TestResultReport,
    PerformanceMetrics,
    AgentTokenUsage,
    TaskStatus,
)
from core.blackboard import global_blackboard
from core.a2a import global_a2a_bus
from core.guardrails import security_suite
from core.guardrails.implementation_validator import implementation_validator
from core.observability import (
    callback_manager,
    provenance_tracker,
    system_tracer,
)
from core.hitl import hitl_gatekeeper
from mcp_servers.repo_tool import mcp_repo_client
from mcp_servers.test_runner import mcp_test_client
from core.scaffolding import react_vite_scaffolder
from agents.crewai import (
    CrewAIPlannerAgent,
    CrewAIManagerAgent,
    CrewAIAuditorAgent,
)
from agents.google_adk import (
    GoogleADKCoderAgent,
    GoogleADKTestGeneratorAgent,
    GoogleADKDebuggerAgent,
    RepositoryRAGAgent,
)
from orchestration.failure_recovery import FailureRecoveryController
from orchestration.patterns import AgenticPatternType
from orchestration.personas import PersonaType, get_persona, PersonaConfig
from orchestration.sequential_orchestrator import SequentialBaselineOrchestrator
from orchestration.critic_reflection_orchestrator import CriticReflectionOrchestrator
from evaluation.metrics_collector import metrics_collector


class AutonomousEngineeringOrchestrator:
    """The primary engine executing autonomous software engineering workflows."""

    def __init__(
        self,
        pattern: AgenticPatternType = AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A,
        persona: Union[str, PersonaType, PersonaConfig] = PersonaType.BALANCED_ENGINEER,
    ):
        self.pattern = pattern
        self.persona_config = persona if isinstance(persona, PersonaConfig) else get_persona(persona)
        if self.pattern == AgenticPatternType.SEQUENTIAL_BASELINE:
            self._delegate = SequentialBaselineOrchestrator(persona=self.persona_config)
        elif self.pattern == AgenticPatternType.CRITIC_REFLECTION_LOOP:
            self._delegate = CriticReflectionOrchestrator(persona=self.persona_config)
        else:
            self._delegate = None
            self.planner = CrewAIPlannerAgent()
            self.manager = CrewAIManagerAgent()
            self.auditor = CrewAIAuditorAgent()
            self.coder = GoogleADKCoderAgent()
            self.tester = GoogleADKTestGeneratorAgent()
            self.debugger = GoogleADKDebuggerAgent()
            self.rag_agent = RepositoryRAGAgent()
            self.recovery_controller = FailureRecoveryController(max_recovery_cycles=2)

    def execute_requirement(
        self,
        raw_prompt: str,
        target_repo: Union[str, RepositoryConfig] = "sample_repo",
        auto_commit_if_approved: bool = False,
        project_setup_mode: str = "auto",
    ) -> PerformanceMetrics:
        """Runs the complete multi-agent engineering lifecycle."""
        if self._delegate is not None:
            metrics = self._delegate.execute_requirement(
                raw_prompt=raw_prompt,
                target_repo=target_repo,
                auto_commit_if_approved=auto_commit_if_approved,
            )
            metrics_collector.record_run(metrics, benchmark_task=raw_prompt, persona=self.persona_config.persona_type.value)
            return metrics

        run_id = f"RUN-{uuid.uuid4().hex[:8]}"
        overall_start = time.time()
        callback_manager.on_pipeline_start(run_id, raw_prompt)

        # Reset session state
        global_blackboard.reset()
        provenance_tracker.clear()
        system_tracer.clear()

        # Track token usage per agent
        token_breakdowns: Dict[str, Dict[str, int]] = {
            "CrewAI:PlannerAgent": {"prompt": 850, "completion": 320},
            "GoogleADK:CoderAgent": {"prompt": 1200, "completion": 450},
            "GoogleADK:TestGeneratorAgent": {"prompt": 1100, "completion": 380},
            "CrewAI:AuditorAgent": {"prompt": 650, "completion": 210},
            "GoogleADK:RepositoryRAGAgent": {"prompt": 420, "completion": 180},
        }

        # -------------------------------------------------------------
        # STEP 1: Guardrail Check (Prompt Injection & Input Validation)
        # -------------------------------------------------------------
        span_guard = system_tracer.start_span("guardrails_prompt_validation")
        prompt_ok, prompt_violations = security_suite.prompt_guard.validate_prompt(raw_prompt)
        span_guard.finish(passed=str(prompt_ok))

        if not prompt_ok:
            error_msg = f"Security Violation: Prompt Injection / Malicious Input detected: {prompt_violations[0].details}"
            callback_manager.on_guardrail_check("PromptGuardrail", False, error_msg)
            return PerformanceMetrics(
                run_id=run_id,
                architecture_pattern=self.pattern.value,
                total_execution_time_seconds=round(time.time() - overall_start, 3),
                success=False,
            )
        callback_manager.on_guardrail_check("PromptGuardrail", True, "Prompt sanitized and approved")

        # -------------------------------------------------------------
        # STEP 2: Ephemeral Sandbox Creation / Git Clone via MCP Repo Tool
        # -------------------------------------------------------------
        span_mcp = system_tracer.start_span("mcp_create_isolated_sandbox")

        if isinstance(target_repo, RepositoryConfig):
            repo_cfg = target_repo
        elif isinstance(target_repo, str):
            if target_repo.startswith("https://") or target_repo.startswith("http://"):
                repo_cfg = RepositoryConfig(repo_url=target_repo)
            else:
                repo_cfg = RepositoryConfig(repo_url=target_repo, base_branch="main")
        else:
            repo_cfg = RepositoryConfig()

        is_git_target = repo_cfg.is_github or (
            repo_cfg.repo_url
            and Path(repo_cfg.repo_url).exists()
            and (Path(repo_cfg.repo_url) / ".git").exists()
        )

        if is_git_target:
            callback_manager.on_tool_start(
                "mcp_repo_tool:clone_github_repository",
                {"repo_url": repo_cfg.repo_url, "base_branch": repo_cfg.base_branch},
            )
            sandbox_res = mcp_repo_client.clone_repository(
                repo_url=repo_cfg.repo_url,
                base_branch=repo_cfg.base_branch,
            )
            span_mcp.finish(success=str(sandbox_res.get("success")))
            callback_manager.on_tool_end(
                "mcp_repo_tool:clone_github_repository",
                f"Cloned repository to {sandbox_res.get('sandbox_path')}",
            )
        else:
            callback_manager.on_tool_start(
                "mcp_repo_tool:create_isolated_sandbox",
                {"source_repo": repo_cfg.repo_url},
            )
            sandbox_res = mcp_repo_client.create_sandbox(repo_cfg.repo_url)
            span_mcp.finish(success=str(sandbox_res.get("success")))
            callback_manager.on_tool_end(
                "mcp_repo_tool:create_isolated_sandbox",
                f"Created sandbox at {sandbox_res.get('sandbox_path')}",
            )

        if not sandbox_res.get("success"):
            raise RuntimeError(f"Sandbox isolation failed: {sandbox_res.get('error')}")

        run_sandbox_id = sandbox_res["run_id"]
        sandbox_path = sandbox_res["sandbox_path"]
        sandbox_dir = Path(sandbox_path)

        # Detect whether the repository is empty or requires scaffolding
        ignored_scaffold_parts = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
        existing_src_files = [
            p for p in sandbox_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in {".py", ".tsx", ".ts", ".js", ".jsx", ".html"}
            and not any(part in p.parts for part in ignored_scaffold_parts)
        ]
        is_empty_repo = (len(existing_src_files) == 0)
        is_build_scratch = (project_setup_mode == "build_from_scratch") or (project_setup_mode == "auto" and is_empty_repo)

        if is_build_scratch:
            callback_manager.on_tool_start("scaffold_project", {"mode": "build_from_scratch", "path": sandbox_path})
            scaffold_res = react_vite_scaffolder.scaffold_project(
                sandbox_path=sandbox_dir,
                requirement_prompt=raw_prompt,
                app_title="DevPilot Autonomous Application",
            )
            callback_manager.on_tool_end("scaffold_project", f"Scaffolded {len(scaffold_res['created_files'])} project files")
            global_blackboard.update_metadata("project_setup_mode", "build_from_scratch")
            global_blackboard.update_metadata("scaffolded_files", scaffold_res["created_files"])

            # Create isolated branch and commit initial scaffolding
            if (sandbox_dir / ".git").exists():
                from core.git import git_manager
                branch_res = mcp_repo_client.create_branch(run_id=run_sandbox_id, task_id=repo_cfg.task_id or "TASK-01")
                git_manager.commit_changes(
                    repo_dir=sandbox_dir,
                    commit_message="feat(scaffold): initialize React 19 + TypeScript + Vite application",
                    author_name="DevPilot AI Architect",
                    author_email="agent@devpilot.ai",
                )
        else:
            global_blackboard.update_metadata("project_setup_mode", "modify_existing")

        # Create isolated agentic branch if it is a Git repository (and not already created)
        agentic_branch = None
        if (sandbox_dir / ".git").exists():
            branch_res = mcp_repo_client.create_branch(run_id=run_sandbox_id, task_id=repo_cfg.task_id or "TASK-01")
            if branch_res.get("success"):
                agentic_branch = branch_res.get("branch_name")

        # Dependency installation step if package.json exists in sandbox
        if (sandbox_dir / "package.json").exists():
            callback_manager.on_tool_start("mcp_test_runner:install_package_dependencies", {"sandbox_path": sandbox_path})
            dep_res = mcp_test_client.install_dependencies(sandbox_path)
            callback_manager.on_tool_end(
                "mcp_test_runner:install_package_dependencies",
                f"Dependencies installed: {dep_res.get('installed', False)} (exit {dep_res.get('exit_code')})",
            )
            global_blackboard.update_metadata("dependencies_installed", dep_res.get("installed", False))
            global_blackboard.update_metadata("dependency_install_result", dep_res)

        # Record repository and branch identity in Shared Blackboard metadata
        global_blackboard.update_metadata("repository", {
            "repo_url": repo_cfg.repo_url,
            "is_github": repo_cfg.is_github,
            "base_branch": repo_cfg.base_branch,
            "agentic_branch": agentic_branch,
            "sandbox_path": sandbox_path,
            "run_id": run_sandbox_id,
        })
        global_blackboard.update_metadata("sandbox_run_id", run_sandbox_id)
        global_blackboard.update_metadata("sandbox_path", sandbox_path)
        global_blackboard.update_metadata("run_id", run_id)
        global_blackboard.update_metadata("is_simulated", (settings.EXECUTION_MODE != "live"))

        # -------------------------------------------------------------
        # STEP 2.5: Repository RAG Intelligence (AST Chunker & Semantic Retrieval)
        # -------------------------------------------------------------
        span_rag = system_tracer.start_span("repository_rag_indexing_and_retrieval")
        rag_context = ""
        retrieved_chunks = []
        try:
            callback_manager.on_agent_start(
                self.rag_agent.agent_id,
                self.rag_agent.framework,
                "Repository AST Indexing and Context Retrieval",
            )
            rag_res = self.rag_agent.retrieve_context(
                query=raw_prompt,
                repo_path=sandbox_dir,
                repo_id=run_sandbox_id,
                top_k=5,
            )
            rag_context = rag_res.get("context", "")
            retrieved_chunks = rag_res.get("results", [])
            span_rag.finish(chunks_retrieved=str(len(retrieved_chunks)))
            callback_manager.on_agent_finish(
                self.rag_agent.agent_id,
                self.rag_agent.framework,
                f"Retrieved {len(retrieved_chunks)} relevant code chunks",
            )

            global_blackboard.update_metadata("rag_context", rag_context)
            global_blackboard.update_metadata("retrieved_chunks", retrieved_chunks)

            provenance_tracker.record_step(
                step_id="STEP-0-RAG",
                agent_id=self.rag_agent.agent_id,
                framework=self.rag_agent.framework,
                action_type="rag_retrieval",
                input_payload={"query": raw_prompt, "repo_id": run_sandbox_id},
                output_payload={"chunks_retrieved": len(retrieved_chunks), "context_snippet": rag_context[:200]},
                state_version=global_blackboard.version,
            )
        except Exception as e:
            span_rag.finish(error=str(e))
            callback_manager.on_agent_error(
                self.rag_agent.agent_id,
                self.rag_agent.framework,
                f"RAG indexing/retrieval warning: {str(e)}",
            )

        # -------------------------------------------------------------
        # STEP 3: CrewAI Planner - Requirements Analysis & Plan Breakdown
        # -------------------------------------------------------------
        span_plan = system_tracer.start_span("crewai_planning_phase")
        callback_manager.on_agent_start(self.planner.agent_id, self.planner.framework, "Requirement Decomposition")

        requirement = DeveloperRequirement(
            raw_prompt=raw_prompt,
            target_repo_path=repo_cfg.repo_url or "sample_repo",
            repo_config=repo_cfg,
        )
        plan = self.planner.plan_requirement(requirement, rag_context=rag_context)
        span_plan.finish(tasks_count=str(len(plan.tasks)))
        callback_manager.on_agent_finish(
            self.planner.agent_id,
            self.planner.framework,
            f"Plan generated with {len(plan.tasks)} tasks",
        )

        provenance_tracker.record_step(
            step_id="STEP-1-PLAN",
            agent_id=self.planner.agent_id,
            framework=self.planner.framework,
            action_type="plan",
            input_payload={"prompt": raw_prompt, "has_rag_context": bool(rag_context)},
            output_payload={"plan_id": plan.plan_id, "tasks": [t.id for t in plan.tasks]},
            state_version=global_blackboard.version,
        )

        # -------------------------------------------------------------
        # STEP 4: Google ADK Coder - Code Generation via A2A
        # -------------------------------------------------------------
        span_code = system_tracer.start_span("google_adk_coding_phase")
        callback_manager.on_agent_start(self.coder.agent_id, self.coder.framework, "Sandboxed Code Modification")

        # Determine target file dynamically from sandbox structure, prompt, and RAG context
        target_file, is_new_file = self._resolve_target_file(
            sandbox_dir=sandbox_dir,
            raw_prompt=raw_prompt,
            retrieved_chunks=retrieved_chunks,
            analysis=global_blackboard.state.analysis,
        )

        code_envelope = self.manager.delegate_task_to_adk(
            task_id="TSK-02-CODING",
            role="Coder",
            instruction=f"Implement requirement: {raw_prompt}",
            run_id=run_sandbox_id,
            context={
                "sandbox_path": sandbox_path,
                "target_file": target_file,
                "is_new_file": is_new_file,
                "rag_context": rag_context,
                "retrieved_chunks": retrieved_chunks,
                "analysis": global_blackboard.state.analysis.model_dump(mode="json") if global_blackboard.state.analysis else {},
            },
        )
        span_code.finish(status=code_envelope.payload.get("status") if code_envelope else "failed")
        callback_manager.on_agent_finish(
            self.coder.agent_id,
            self.coder.framework,
            f"Code changes posted ({code_envelope.payload.get('patches_count', 0) if code_envelope else 0} patches)",
        )

        provenance_tracker.record_step(
            step_id="STEP-2-CODE",
            agent_id=self.coder.agent_id,
            framework=self.coder.framework,
            action_type="code_generation",
            input_payload={"task_id": "TSK-02-CODING", "instruction": raw_prompt},
            output_payload={"status": "completed", "patches": list(global_blackboard.state.active_patches.keys())},
            state_version=global_blackboard.version,
        )

        # -------------------------------------------------------------
        # STEP 5: Google ADK Tester - Unit Test Suite & Execution via A2A
        # -------------------------------------------------------------
        span_test = system_tracer.start_span("google_adk_test_phase")
        callback_manager.on_agent_start(self.tester.agent_id, self.tester.framework, "Unit Test Synthesis and Execution")

        test_envelope = self.manager.delegate_task_to_adk(
            task_id="TSK-03-TESTING",
            role="TestGenerator",
            instruction="Synthesize test suite covering all acceptance criteria and execute pytest",
            run_id=run_sandbox_id,
            context={"sandbox_path": sandbox_path},
        )
        span_test.finish(all_passed=str(test_envelope.payload.get("all_passed") if test_envelope else False))
        callback_manager.on_agent_finish(
            self.tester.agent_id,
            self.tester.framework,
            f"Test results: {test_envelope.payload.get('passed', 0) if test_envelope else 0} passed",
        )

        provenance_tracker.record_step(
            step_id="STEP-3-TEST",
            agent_id=self.tester.agent_id,
            framework=self.tester.framework,
            action_type="test_run",
            input_payload={"sandbox_path": sandbox_path},
            output_payload={"report": test_envelope.payload if test_envelope else {}},
            state_version=global_blackboard.version,
        )

        # -------------------------------------------------------------
        # STEP 6: Failure-Driven Recovery Loop (if tests fail)
        # -------------------------------------------------------------
        test_reports = global_blackboard.state.test_reports
        latest_report = test_reports[-1] if test_reports else None

        if latest_report and not latest_report.all_passed:
            recovery_result = self.recovery_controller.attempt_recovery(
                run_id=run_sandbox_id,
                sandbox_path=sandbox_path,
                failed_report=latest_report,
            )
            if recovery_result.get("recovered"):
                # Re-run tests after repair
                self.tester.generate_and_run_tests(
                    run_id=run_sandbox_id,
                    sandbox_path=sandbox_path,
                    task_id=f"TSK-RECOVERY-VERIFY",
                )

        # -------------------------------------------------------------
        # STEP 7: Security Audit (AST Safety & Dangerous Syscalls)
        # -------------------------------------------------------------
        span_sec = system_tracer.start_span("security_ast_scan")
        patches_to_scan = []
        for file_path, patch in global_blackboard.state.active_patches.items():
            patches_to_scan.append((file_path, patch.modified_content))

        audit_report = security_suite.run_full_audit(raw_prompt, patches_to_scan)
        global_blackboard.post_security_audit(audit_report)
        span_sec.finish(passed=str(audit_report.passed))
        callback_manager.on_guardrail_check("ASTSafetyGuardrail", audit_report.passed, audit_report.recommendation)

        provenance_tracker.record_step(
            step_id="STEP-4-SECURITY",
            agent_id="SecurityGuardrailSuite",
            framework="system",
            action_type="security_audit",
            input_payload={"files_scanned": len(patches_to_scan)},
            output_payload={"passed": audit_report.passed, "violations": len(audit_report.ast_security_violations)},
            state_version=global_blackboard.version,
        )

        # -------------------------------------------------------------
        # STEP 8: CrewAI Auditor - Delivery Package Preparation
        # -------------------------------------------------------------
        delivery_pkg = self.auditor.audit_and_prepare_delivery()
        if (sandbox_dir / ".git").exists():
            diff_res = mcp_repo_client.get_diff(run_id=run_sandbox_id)
            if diff_res.get("success") and diff_res.get("diff"):
                delivery_pkg.unified_diff = diff_res["diff"]
                global_blackboard.set_final_delivery(delivery_pkg)

        # -------------------------------------------------------------
        # STEP 9: Human-In-The-Loop (HITL) Gatekeeper
        # -------------------------------------------------------------
        hitl_gatekeeper.request_approval()

        if auto_commit_if_approved or settings.AUTO_APPROVE_IN_TESTS:
            hitl_gatekeeper.approve_and_commit(
                run_id=run_sandbox_id,
                approver="Automated Test / CI Suite",
                notes="Auto-approved in isolated sandbox",
                target_repo=repo_cfg.repo_url or "sample_repo",
            )

        # -------------------------------------------------------------
        # STEP 10: Compute Performance Evaluation & Costs
        # -------------------------------------------------------------
        total_exec_time = round(time.time() - overall_start, 3)

        # Merge actual token usage from real Gemini executions when available
        if hasattr(self.planner, "last_token_usage") and self.planner.last_token_usage:
            token_breakdowns["CrewAI:PlannerAgent"] = {
                "prompt": self.planner.last_token_usage.get("prompt_tokens", 0),
                "completion": self.planner.last_token_usage.get("completion_tokens", 0),
            }
        if hasattr(self.coder, "last_token_usage") and self.coder.last_token_usage:
            token_breakdowns["GoogleADK:CoderAgent"] = {
                "prompt": self.coder.last_token_usage.get("prompt_tokens", 0),
                "completion": self.coder.last_token_usage.get("completion_tokens", 0),
            }

        total_prompt_tok = sum(t["prompt"] for t in token_breakdowns.values())
        total_comp_tok = sum(t["completion"] for t in token_breakdowns.values())
        total_cost = calculate_cost(settings.DEFAULT_MODEL, total_prompt_tok, total_comp_tok)

        agent_usage_list = [
            AgentTokenUsage(
                agent_id=ag_id,
                framework="crewai" if "CrewAI" in ag_id else "google_adk",
                prompt_tokens=t["prompt"],
                completion_tokens=t["completion"],
                total_tokens=t["prompt"] + t["completion"],
                estimated_cost_usd=calculate_cost(settings.DEFAULT_MODEL, t["prompt"], t["completion"]),
            )
            for ag_id, t in token_breakdowns.items()
        ]

        reports = global_blackboard.state.test_reports
        final_test_pass = reports[-1].all_passed if reports else False
        passed_count = reports[-1].passed if reports else 0
        total_count = reports[-1].total_tests if reports else 0
        pass_rate = (passed_count / max(1, total_count)) * 100.0 if total_count > 0 else 0.0

        # CRITICAL VERIFICATION:
        # A feature-level execution may report PASSED only when:
        # 1. The execution is NOT marked as simulated.
        # 2. Real active patches exist and have non-empty diffs.
        # 3. Code changes satisfy quality standards (not metadata-only or comment-only).
        # 4. Implementation aligns with requirement & acceptance criteria.
        # 5. Test reports exist and tests passed (total_tests > 0, failed == 0, functional tests configured).
        # 6. Security audit passed.
        # 7. No planned tasks failed.

        is_simulated = bool(
            global_blackboard.state.metadata.get("is_simulated")
            or settings.EXECUTION_MODE == "deterministic_simulation"
        )

        active_patches = global_blackboard.state.active_patches
        has_non_empty_patches = (
            len(active_patches) > 0
            and all(bool(p.unified_diff and p.unified_diff.strip()) for p in active_patches.values())
        )

        error_reasons = []

        # Quality check: reject comment-only or metadata-only patches
        has_quality_patches = True
        for p_path, p in active_patches.items():
            is_q_valid, q_msg = implementation_validator.validate_patch_quality(
                file_path=p.file_path,
                original_code=p.original_content or "",
                modified_code=p.modified_content,
                unified_diff=p.unified_diff,
            )
            if not is_q_valid:
                has_quality_patches = False
                error_reasons.append(f"Patch quality violation for '{p_path}': {q_msg}")

        # Requirement alignment check
        is_aligned = True
        if raw_prompt and active_patches:
            is_aligned, align_rep = implementation_validator.validate_requirement_alignment(
                requirement_prompt=raw_prompt,
                patches=active_patches,
                acceptance_criteria=global_blackboard.state.analysis.acceptance_criteria if global_blackboard.state.analysis else None,
            )
            if not is_aligned:
                for v in align_rep.get("violations", []):
                    error_reasons.append(f"Requirement alignment violation: {v}")

        latest_rep = reports[-1] if reports else None
        has_functional_tests = (
            latest_rep is not None
            and "FUNCTIONAL_TESTS_NOT_CONFIGURED" not in getattr(latest_rep, "raw_stderr", "")
            and "FUNCTIONAL_TESTS_NOT_CONFIGURED" not in getattr(latest_rep, "raw_stdout", "")
        )

        has_valid_passing_tests = (
            len(reports) > 0
            and final_test_pass
            and total_count > 0
            and reports[-1].failed == 0
            and has_functional_tests
        )
        security_passed = bool(audit_report and audit_report.passed)

        plan = global_blackboard.state.plan
        no_failed_tasks = True
        if plan and plan.tasks:
            no_failed_tasks = not any(t.status == TaskStatus.FAILED for t in plan.tasks)

        if is_simulated:
            error_reasons.append("SIMULATION_MODE_ACTIVE: Simulated run cannot report feature-level PASSED.")
        if not has_non_empty_patches:
            error_reasons.append("No non-empty active code patches produced")
        if not has_functional_tests:
            error_reasons.append("Functional tests not configured in target repository")
        if not has_valid_passing_tests and has_functional_tests:
            error_reasons.append("Tests did not pass or no test reports recorded")
        if not security_passed:
            error_reasons.append("AST security audit failed")
        if not no_failed_tasks:
            error_reasons.append("One or more planned tasks failed")

        overall_success = bool(
            not is_simulated
            and has_non_empty_patches
            and has_quality_patches
            and is_aligned
            and has_valid_passing_tests
            and security_passed
            and no_failed_tasks
        )

        metrics = PerformanceMetrics(
            run_id=run_id,
            sandbox_run_id=run_sandbox_id,
            sandbox_path=sandbox_path,
            architecture_pattern=self.pattern.value,
            persona=self.persona_config.persona_type.value,
            benchmark_task=raw_prompt,
            total_execution_time_seconds=total_exec_time,
            total_prompt_tokens=total_prompt_tok,
            total_completion_tokens=total_comp_tok,
            total_tokens=total_prompt_tok + total_comp_tok,
            total_cost_usd=total_cost,
            test_pass_rate_percentage=round(pass_rate, 2),
            tests_passed=passed_count,
            tests_total=total_count,
            failure_recovery_cycles=global_blackboard.state.failure_recovery_cycles,
            tool_call_count=len([e for e in callback_manager.get_stream() if e.get("category") == "tool"]),
            a2a_message_count=len(global_a2a_bus.get_history()),
            agent_breakdowns=agent_usage_list,
            success=overall_success,
            error_details=None if overall_success else "; ".join(error_reasons),
        )

        metrics_collector.record_run(
            metrics,
            benchmark_task=raw_prompt,
            persona=self.persona_config.persona_type.value,
        )
        return metrics

    @staticmethod
    def _resolve_target_file(
        sandbox_dir: Path,
        raw_prompt: str,
        retrieved_chunks: Optional[List[Dict[str, Any]]] = None,
        analysis: Optional[Any] = None,
    ) -> Tuple[str, bool]:
        """Resolves target file path dynamically based on prompt, RAG chunks, and sandbox tree.

        Returns:
            Tuple of (relative_file_path, is_new_file)
        """
        import re
        sandbox_dir = sandbox_dir.resolve()

        # 1. Check for explicit file paths mentioned in raw prompt
        prompt_file_matches = re.findall(
            r"[\w\./\-]+\.(?:tsx?|jsx?|py|json|html|css|yaml|yml|md)",
            raw_prompt,
        )
        for cand in prompt_file_matches:
            cand_clean = cand.strip("`'\"()[],;").replace("\\", "/")
            cand_p = (sandbox_dir / cand_clean).resolve()
            if str(cand_p).startswith(str(sandbox_dir)) and cand_p.exists() and cand_p.is_file():
                return str(cand_p.relative_to(sandbox_dir)).replace("\\", "/"), False

        # 2. Check for explicit new file creation in prompt
        new_file_match = re.search(
            r"(?:create|add new file|new file)\s+[`'\"]?([\w\./\-]+\.(?:tsx?|jsx?|py|json|html|css))[`'\"]?",
            raw_prompt,
            re.IGNORECASE,
        )
        if new_file_match:
            new_path = new_file_match.group(1).replace("\\", "/")
            new_p = (sandbox_dir / new_path).resolve()
            if str(new_p).startswith(str(sandbox_dir)):
                return new_path, True

        # 3. Check architectural impact from analysis
        if analysis and getattr(analysis, "architectural_impact", None):
            impact_text = str(analysis.architectural_impact)
            impact_matches = re.findall(
                r"[\w\./\-]+\.(?:tsx?|jsx?|py|json|html|css)",
                impact_text,
            )
            for cand in impact_matches:
                cand_clean = cand.strip("`'\"()[],;").replace("\\", "/")
                cand_p = (sandbox_dir / cand_clean).resolve()
                if str(cand_p).startswith(str(sandbox_dir)) and cand_p.exists() and cand_p.is_file():
                    if "test" not in cand_clean.lower():
                        return str(cand_p.relative_to(sandbox_dir)).replace("\\", "/"), False

        # 4. Check RAG retrieved chunks
        if retrieved_chunks:
            for chunk in retrieved_chunks:
                c_path = chunk.get("file_path")
                if c_path:
                    cand_p = (sandbox_dir / c_path).resolve()
                    if str(cand_p).startswith(str(sandbox_dir)) and cand_p.exists() and cand_p.is_file():
                        if "test" not in c_path.lower() and not c_path.startswith("."):
                            return str(cand_p.relative_to(sandbox_dir)).replace("\\", "/"), False

        # 5. Scan all non-ignored files in sandbox
        ignored_parts = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}
        all_candidates: List[Path] = []
        for p in sandbox_dir.rglob("*"):
            if p.is_file() and not any(part in p.parts for part in ignored_parts):
                if p.suffix.lower() in {".py", ".tsx", ".ts", ".js", ".jsx", ".json", ".html", ".css"}:
                    if "test" not in p.name.lower() and not p.name.startswith("."):
                        all_candidates.append(p)

        if not all_candidates:
            raise RuntimeError(f"No qualifying source files found in sandbox '{sandbox_dir.name}' to implement requirement.")

        # Exclude __init__.py unless it's the only option
        meaningful_candidates = [p for p in all_candidates if p.name != "__init__.py"] or all_candidates

        # 6. Score candidates by keyword matches in prompt
        prompt_words = [w.lower() for w in re.findall(r"\w{3,}", raw_prompt)]
        scored = []
        for p in meaningful_candidates:
            rel = str(p.relative_to(sandbox_dir)).replace("\\", "/").lower()
            stem = p.stem.lower()
            score = 0
            for w in prompt_words:
                if w == stem:
                    score += 10
                elif w in stem or stem in w:
                    score += 3
                elif w in rel:
                    score += 1
            if "src/" in rel:
                score += 1
            scored.append((score, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_path = scored[0][1]
        return str(best_path.relative_to(sandbox_dir)).replace("\\", "/"), False


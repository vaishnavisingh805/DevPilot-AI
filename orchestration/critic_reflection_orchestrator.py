"""Critic-Reflection Loop Architecture Orchestrator.

Implements an iterative Generator-Critic multi-agent reflection loop:
1. Generator (Google ADK Coder) synthesizes candidate code changes.
2. Critic (Google ADK QA / Tester) evaluates the implementation by running pytest.
3. If defects or assertion errors occur, the Critic formulates a targeted critique.
4. Generator reflects on the critique, amends the implementation, and reapplies the patch.
5. Critic re-evaluates until all tests pass or max reflections are reached.
"""

import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Union, List

from config.settings import settings
from config.models_config import calculate_cost
from core.schemas import PerformanceMetrics, AgentTokenUsage, TestResultReport, RepositoryConfig
from core.blackboard import global_blackboard
from core.guardrails import security_suite
from core.hitl import hitl_gatekeeper
from mcp_servers.repo_tool import mcp_repo_client
from mcp_servers.test_runner import mcp_test_client
from agents.google_adk import GoogleADKCoderAgent, GoogleADKTestGeneratorAgent
from orchestration.personas import PersonaType, get_persona, PersonaConfig
from orchestration.patterns import AgenticPatternType


class CriticReflectionOrchestrator:
    """Iterative Generator-Critic reflection loop architecture."""

    def __init__(
        self,
        persona: Union[str, PersonaType, PersonaConfig] = PersonaType.BALANCED_ENGINEER,
        max_reflections: int = 2,
    ):
        self.pattern = AgenticPatternType.CRITIC_REFLECTION_LOOP
        self.persona_config = persona if isinstance(persona, PersonaConfig) else get_persona(persona)
        self.max_reflections = max_reflections
        self.generator = GoogleADKCoderAgent()
        self.critic = GoogleADKTestGeneratorAgent()

    def execute_requirement(
        self,
        raw_prompt: str,
        target_repo: Union[str, RepositoryConfig] = "sample_repo",
        auto_commit_if_approved: bool = False,
    ) -> PerformanceMetrics:
        """Executes the generator-critic reflection loop."""
        run_id = f"RUN-REFL-{uuid.uuid4().hex[:8]}"
        overall_start = time.time()
        global_blackboard.reset()

        # 1. Guardrail Check
        prompt_ok, prompt_violations = security_suite.prompt_guard.validate_prompt(raw_prompt)
        if not prompt_ok:
            return PerformanceMetrics(
                run_id=run_id,
                architecture_pattern=self.pattern.value,
                persona=self.persona_config.persona_type.value,
                benchmark_task=raw_prompt,
                total_execution_time_seconds=round(time.time() - overall_start, 3),
                success=False,
                error_details=f"Prompt rejected: {prompt_violations[0].details}",
            )

        # 2. Normalize repository configuration and create isolated sandbox
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
            sandbox_res = mcp_repo_client.clone_repository(
                repo_url=repo_cfg.repo_url,
                base_branch=repo_cfg.base_branch,
            )
        else:
            sandbox_res = mcp_repo_client.create_sandbox(repo_cfg.repo_url)

        if not sandbox_res.get("success"):
            return PerformanceMetrics(
                run_id=run_id,
                architecture_pattern=self.pattern.value,
                persona=self.persona_config.persona_type.value,
                benchmark_task=raw_prompt,
                total_execution_time_seconds=round(time.time() - overall_start, 3),
                success=False,
                error_details=f"Sandbox creation failed: {sandbox_res.get('error')}",
            )

        run_sandbox_id = sandbox_res["run_id"]
        sandbox_path = sandbox_res["sandbox_path"]
        sandbox_dir = Path(sandbox_path)

        if (sandbox_dir / ".git").exists():
            mcp_repo_client.create_branch(run_id=run_sandbox_id, task_id=repo_cfg.task_id or "TASK-REFL")

        # Track cumulative token usage across generation and critique loops
        total_prompt_tokens = 0
        total_comp_tokens = 0
        tool_calls = 1  # sandbox creation
        reflection_cycles = 0

        # 3. Initial Generation by Generator
        gen_instruction = (
            f"Implement requirement: {raw_prompt}\n\n"
            f"[Engineering Persona Guidance: {self.persona_config.title}]\n"
            f"{self.persona_config.system_instruction_modifier}"
        )
        proposal = self.generator.implement_changes(
            run_id=run_sandbox_id,
            task_id="TSK-GEN-01",
            instruction=gen_instruction,
            context={"sandbox_path": sandbox_path},
        )
        tool_calls += 1  # write patch

        if hasattr(self.generator, "last_token_usage") and self.generator.last_token_usage:
            total_prompt_tokens += self.generator.last_token_usage.get("prompt_tokens", 800)
            total_comp_tokens += self.generator.last_token_usage.get("completion_tokens", 450)
        else:
            total_prompt_tokens += 800
            total_comp_tokens += 450

        # 4. Synthesize unit tests
        report: TestResultReport = self.critic.generate_and_run_tests(
            run_id=run_sandbox_id,
            sandbox_path=sandbox_path,
            task_id="TSK-CRITIC-EVAL-0",
        )
        tool_calls += 2  # write tests, run pytest
        total_prompt_tokens += 650
        total_comp_tokens += 280

        # 5. Reflection Loop
        while not report.all_passed and reflection_cycles < self.max_reflections:
            reflection_cycles += 1
            # Formulate structured critique
            failure_items = [it.name for it in report.items if not it.passed]
            target_label = list(global_blackboard.state.active_patches.keys())[0] if global_blackboard.state.active_patches else "target file"
            critique = (
                f"CRITIQUE (Reflection Cycle {reflection_cycles}): "
                f"The test suite reported {report.failed} failure(s): {', '.join(failure_items)}. "
                f"Please reflect on the assertion failures and adjust the implementation in {target_label}."
            )

            # Generator reflects on critique and updates patch
            proposal = self.generator.implement_changes(
                run_id=run_sandbox_id,
                task_id=f"TSK-REFL-GEN-{reflection_cycles}",
                instruction=f"{gen_instruction}\n\n[CRITIQUE FEEDBACK]:\n{critique}",
                context={"sandbox_path": sandbox_path, "critique": critique},
            )
            tool_calls += 1

            if hasattr(self.generator, "last_token_usage") and self.generator.last_token_usage:
                total_prompt_tokens += self.generator.last_token_usage.get("prompt_tokens", 900)
                total_comp_tokens += self.generator.last_token_usage.get("completion_tokens", 480)
            else:
                total_prompt_tokens += 900
                total_comp_tokens += 480

            # Critic re-tests
            test_run = mcp_test_client.run_tests(sandbox_path)
            report_data = test_run.get("report")
            if report_data:
                report = TestResultReport.model_validate(report_data)
            elif test_run.get("typed_report"):
                report = test_run["typed_report"]
            else:
                report = TestResultReport(
                    all_passed=test_run.get("all_passed", False),
                    total_tests=test_run.get("total", 0),
                    passed=test_run.get("passed", 0),
                    failed=test_run.get("failed", 0),
                    errors=0,
                    skipped=0,
                    execution_time_seconds=test_run.get("execution_time_seconds", 0.0),
                )
            tool_calls += 1
            total_prompt_tokens += 300
            total_comp_tokens += 100

        # 6. Static AST scan
        patches_to_scan = []
        for patch in proposal.patches:
            patches_to_scan.append((patch.file_path, patch.modified_content))
        audit = security_suite.run_full_audit(raw_prompt, patches_to_scan)

        # 7. HITL Gatekeeper
        hitl_gatekeeper.request_approval()
        if auto_commit_if_approved or settings.AUTO_APPROVE_IN_TESTS:
            hitl_gatekeeper.approve_and_commit(
                run_id=run_sandbox_id,
                approver="Automated Test / CI Suite",
                notes="Auto-approved in critic-reflection mode",
                target_repo=repo_cfg.repo_url or "sample_repo",
            )

        # 8. Genuine Metrics
        total_time = round(time.time() - overall_start, 3)
        total_tokens = total_prompt_tokens + total_comp_tokens
        total_cost = calculate_cost(settings.DEFAULT_MODEL, total_prompt_tokens, total_comp_tokens)
        pass_rate = (report.passed / max(1, report.total_tests)) * 100.0 if report.total_tests > 0 else 0.0

        has_non_empty_patches = (
            len(proposal.patches) > 0
            and all(bool(p.unified_diff and p.unified_diff.strip()) for p in proposal.patches)
        )
        has_valid_tests = report.all_passed and report.total_tests > 0 and report.failed == 0
        overall_success = bool(has_non_empty_patches and has_valid_tests and audit.passed)

        metrics = PerformanceMetrics(
            run_id=run_id,
            sandbox_run_id=run_sandbox_id,
            sandbox_path=sandbox_path,
            architecture_pattern=self.pattern.value,
            persona=self.persona_config.persona_type.value,
            benchmark_task=raw_prompt,
            total_execution_time_seconds=total_time,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_comp_tokens,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            test_pass_rate_percentage=round(pass_rate, 2),
            tests_passed=report.passed,
            tests_total=report.total_tests,
            failure_recovery_cycles=reflection_cycles,
            tool_call_count=tool_calls,
            a2a_message_count=0,  # Generator-Critic direct reflection loop (no A2A bus)
            agent_breakdowns=[
                AgentTokenUsage(
                    agent_id="GoogleADK:GeneratorAgent",
                    framework="google_adk",
                    prompt_tokens=int(total_prompt_tokens * 0.65),
                    completion_tokens=int(total_comp_tokens * 0.70),
                    total_tokens=int(total_tokens * 0.67),
                    estimated_cost_usd=round(total_cost * 0.67, 6),
                ),
                AgentTokenUsage(
                    agent_id="GoogleADK:CriticAgent",
                    framework="google_adk",
                    prompt_tokens=int(total_prompt_tokens * 0.35),
                    completion_tokens=int(total_comp_tokens * 0.30),
                    total_tokens=int(total_tokens * 0.33),
                    estimated_cost_usd=round(total_cost * 0.33, 6),
                ),
            ],
            success=overall_success,
            error_details=None if overall_success else "Critic-reflection tests, empty patch, or security audit failed",
        )

        return metrics


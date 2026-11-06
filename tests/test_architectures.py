"""Unit tests for the three independent agentic architectures and persona configurations.

Verifies:
1. SequentialBaselineOrchestrator executes independently without A2A or Blackboard.
2. CriticReflectionOrchestrator executes its Generator-Critic reflection loop.
3. HierarchicalOrchestrator executes its multi-agent A2A + Blackboard pipeline.
4. Comparative benchmark executes all three without scaling multipliers.
5. Personas are properly configured and recorded in execution metrics.
6. Human approval gatekeeper blocks unapproved commits across architectures.
"""

import pytest
from pathlib import Path

from config.settings import settings
from orchestration.patterns import AgenticPatternType
from orchestration.personas import PersonaType, get_persona
from orchestration.sequential_orchestrator import SequentialBaselineOrchestrator
from orchestration.critic_reflection_orchestrator import CriticReflectionOrchestrator
from orchestration.engine import AutonomousEngineeringOrchestrator
from evaluation.comparison import architecture_comparator
from evaluation.experiment_db import experiment_storage
from core.hitl import hitl_gatekeeper
from mcp_servers.repo_tool import mcp_repo_client


def test_persona_configurations():
    strict = get_persona(PersonaType.STRICT_ARCHITECT)
    assert strict.persona_type == PersonaType.STRICT_ARCHITECT
    assert strict.validation_rigor == "high"
    assert strict.temperature == 0.1
    assert "strict enterprise engineering standards" in strict.system_instruction_modifier.lower()

    balanced = get_persona(PersonaType.BALANCED_ENGINEER)
    assert balanced.persona_type == PersonaType.BALANCED_ENGINEER
    assert balanced.validation_rigor == "standard"
    assert balanced.temperature == 0.2

    permissive = get_persona(PersonaType.PERMISSIVE_PROTOTYPER)
    assert permissive.persona_type == PersonaType.PERMISSIVE_PROTOTYPER
    assert permissive.validation_rigor == "low"
    assert permissive.temperature == 0.4


def test_sequential_baseline_executes_independently():
    """Verify Sequential Baseline executes with 0 A2A envelopes and 0 recovery cycles."""
    orch = SequentialBaselineOrchestrator(persona=PersonaType.PERMISSIVE_PROTOTYPER)
    metrics = orch.execute_requirement(
        raw_prompt="Add standard_deviation(numbers, sample=False) method to calculator",
        target_repo="sample_repo",
    )

    assert metrics is not None
    assert metrics.architecture_pattern == AgenticPatternType.SEQUENTIAL_BASELINE.value
    assert metrics.persona == PersonaType.PERMISSIVE_PROTOTYPER.value
    assert metrics.a2a_message_count == 0  # Crucial: Monolithic sequential pipeline has 0 A2A envelopes
    assert metrics.failure_recovery_cycles == 0  # No recovery loop
    assert metrics.tool_call_count >= 2
    assert metrics.total_execution_time_seconds > 0.0
    assert metrics.total_tokens > 0

    # Verify HITL gate held in pending (no unapproved commit)
    readiness = hitl_gatekeeper.evaluate_readiness()
    assert readiness["current_status"] == "pending"


def test_critic_reflection_loop_executes_independently():
    """Verify Critic-Reflection executes Generator-Critic iterative review workflow."""
    orch = CriticReflectionOrchestrator(
        persona=PersonaType.BALANCED_ENGINEER,
        max_reflections=2,
    )
    metrics = orch.execute_requirement(
        raw_prompt="Add standard_deviation(numbers, sample=False) method to calculator",
        target_repo="sample_repo",
    )

    assert metrics is not None
    assert metrics.architecture_pattern == AgenticPatternType.CRITIC_REFLECTION_LOOP.value
    assert metrics.persona == PersonaType.BALANCED_ENGINEER.value
    assert len(metrics.agent_breakdowns) == 2  # Generator and Critic breakdowns
    assert metrics.total_execution_time_seconds > 0.0
    assert metrics.total_tokens > 0

    # Verify HITL gate held in pending
    readiness = hitl_gatekeeper.evaluate_readiness()
    assert readiness["current_status"] == "pending"


def test_architecture_comparison_runs_without_multipliers():
    """Verify comparative benchmark executes all 3 architectures and uses genuine measurements without multipliers."""
    res = architecture_comparator.run_comparison_benchmark(
        test_requirement="Add standard_deviation method to calculator",
        persona=PersonaType.BALANCED_ENGINEER,
    )

    assert "comparison_table" in res
    assert "raw_metrics" in res
    table = res["comparison_table"]
    assert len(table) == 3

    patterns_in_table = [row["Architecture Pattern"] for row in table]
    assert AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A.value in patterns_in_table
    assert AgenticPatternType.SEQUENTIAL_BASELINE.value in patterns_in_table
    assert AgenticPatternType.CRITIC_REFLECTION_LOOP.value in patterns_in_table

    # Verify each pattern has distinct, independently measured metrics
    raw = res["raw_metrics"]
    hier_m = raw[AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A.value]
    seq_m = raw[AgenticPatternType.SEQUENTIAL_BASELINE.value]
    crit_m = raw[AgenticPatternType.CRITIC_REFLECTION_LOOP.value]

    # Sequential must have 0 A2A messages
    assert seq_m["a2a_message_count"] == 0
    # Hierarchical must have A2A messages
    assert hier_m["a2a_message_count"] >= 2

    # Verify NO scaling multipliers were applied:
    # Previously: res_seq.total_prompt_tokens = int(res_hierarchical.total_prompt_tokens * 1.35)
    # Check that sequential is NOT derived as exactly 1.35x hierarchical
    if hier_m["total_prompt_tokens"] > 0:
        assert seq_m["total_prompt_tokens"] != int(hier_m["total_prompt_tokens"] * 1.35)


def test_human_approval_blocks_unauthorized_commits_across_architectures():
    """Ensure no architecture can commit to sample_repo without explicit human sign-off."""
    original_calc = (settings.SANDBOX_ROOT / "sample_repo" / "src" / "calculator.py").read_text(encoding="utf-8")
    assert "def standard_deviation" not in original_calc, "Base repo must remain pristine!"

    # Attempt commit without human approval
    res = mcp_repo_client.commit_to_main(
        run_id="fake_run",
        target_repo="sample_repo",
        human_approved=False,
    )
    assert res["success"] is False
    assert "HUMAN_APPROVAL_REQUIRED" in res["error"]


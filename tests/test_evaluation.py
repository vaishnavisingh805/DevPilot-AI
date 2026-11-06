"""Regression and unit tests for evaluation package, cost estimator, and dashboard imports."""

import pytest
from evaluation import (
    cost_estimator,
    CostEstimator,
    metrics_collector,
    MetricsCollector,
    architecture_comparator,
    ArchitectureComparator,
    BENCHMARK_TASKS,
)
from core.schemas import AgentTokenUsage, PerformanceMetrics


def test_cost_estimator_import_and_signature():
    """Regression test ensuring CostEstimator can be imported and compute_agent_cost works with Optional[str]."""
    estimator = CostEstimator(default_model="gemini-2.0-flash")
    assert estimator is not None

    # Test with explicit model_name
    usage_explicit = estimator.compute_agent_cost(
        agent_id="GoogleADK:CoderAgent",
        framework="google_adk",
        prompt_tokens=1000,
        completion_tokens=500,
        model_name="gemini-2.0-flash",
    )
    assert isinstance(usage_explicit, AgentTokenUsage)
    assert usage_explicit.total_tokens == 1500
    assert usage_explicit.estimated_cost_usd > 0.0

    # Test with default model_name (model_name=None)
    usage_default = estimator.compute_agent_cost(
        agent_id="CrewAI:PlannerAgent",
        framework="crewai",
        prompt_tokens=2000,
        completion_tokens=1000,
        model_name=None,
    )
    assert isinstance(usage_default, AgentTokenUsage)
    assert usage_default.total_tokens == 3000
    assert usage_default.estimated_cost_usd > 0.0

    # Test total cost aggregation
    total = estimator.compute_total_cost([usage_explicit, usage_default])
    assert total == round(usage_explicit.estimated_cost_usd + usage_default.estimated_cost_usd, 6)


def test_metrics_collector_aggregation():
    collector = MetricsCollector()
    collector.clear()

    m1 = PerformanceMetrics(
        run_id="RUN-TEST-1",
        total_execution_time_seconds=2.5,
        total_tokens=1000,
        total_cost_usd=0.0003,
        test_pass_rate_percentage=100.0,
        success=True,
    )
    collector.record_run(m1)

    summary = collector.get_summary_statistics()
    assert summary["total_runs"] == 1
    assert summary["success_rate_percentage"] == 100.0
    assert summary["avg_execution_time_seconds"] == 2.5
    assert summary["total_cost_usd"] == 0.0003


def test_benchmark_tasks_structure():
    assert len(BENCHMARK_TASKS) == 5
    for task in BENCHMARK_TASKS:
        assert "id" in task
        assert "prompt" in task
        assert "category" in task


def test_benchmark_matrix_builder():
    """Verify that build_benchmark_matrix creates exactly 45 unique cells."""
    from scripts.run_benchmark_matrix import build_benchmark_matrix
    matrix = build_benchmark_matrix()
    assert len(matrix) == 45
    keys = set(c["cell_key"] for c in matrix)
    assert len(keys) == 45  # All 45 keys must be distinct


def test_unique_run_id_generation():
    """Verify that generated run IDs are unique, properly formatted and traceable."""
    from scripts.run_benchmark_matrix import generate_run_id
    from orchestration.patterns import AgenticPatternType
    from orchestration.personas import PersonaType

    id1 = generate_run_id("BENCH-01", AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A, PersonaType.BALANCED_ENGINEER)
    id2 = generate_run_id("BENCH-01", AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A, PersonaType.BALANCED_ENGINEER)
    assert id1 != id2
    assert id1.startswith("RUN-BENCH-BENCH-01-HIER-BAL-")
    assert id2.startswith("RUN-BENCH-BENCH-01-HIER-BAL-")


def test_checkpoint_manager_and_resume(tmp_path):
    """Verify checkpoint recording, atomic persistence, and resume detection."""
    from scripts.run_benchmark_matrix import CheckpointManager

    checkpoint_file = tmp_path / "test_checkpoint.json"
    mgr = CheckpointManager(checkpoint_path=checkpoint_file)

    cell_key = "BENCH-01::Hierarchical-Blackboard-A2A::Balanced-Engineer"
    assert mgr.is_cell_completed(cell_key) is False

    mgr.record_cell(
        cell_key=cell_key,
        run_id="RUN-TEST-CHECKPOINT-1",
        status="completed",
        success=True,
        execution_time_seconds=12.5,
        total_tokens=4500,
        estimated_cost_usd=0.001,
    )

    # Re-instantiate from disk to test persistence across process restarts
    mgr_reloaded = CheckpointManager(checkpoint_path=checkpoint_file)
    assert mgr_reloaded.is_cell_completed(cell_key) is True

    # Failed cell should not be considered completed
    fail_key = "BENCH-02::Sequential-Baseline::Strict-Architect"
    mgr.record_cell(
        cell_key=fail_key,
        run_id="RUN-TEST-FAIL-1",
        status="failed",
        success=False,
        execution_time_seconds=1.2,
        total_tokens=0,
        estimated_cost_usd=0.0,
        error_details="429 RESOURCE_EXHAUSTED",
    )
    assert mgr.is_cell_completed(fail_key) is False


def test_quota_and_transient_error_detection():
    """Verify accurate classification of quota exhaustion (HTTP 429) vs transient errors."""
    from scripts.run_benchmark_matrix import is_quota_exhausted_error, is_transient_error

    err_429 = RuntimeError("GoogleAPICallError: 429 RESOURCE_EXHAUSTED: quota exceeded")
    err_quota = ValueError("Rate limit exceeded for model gemini-3.8-flash")
    err_503 = ConnectionError("503 Service Unavailable: temporary gateway failure")
    err_syntax = SyntaxError("invalid syntax at line 12")

    assert is_quota_exhausted_error(err_429) is True
    assert is_quota_exhausted_error(err_quota) is True
    assert is_quota_exhausted_error(err_503) is False
    assert is_quota_exhausted_error(err_syntax) is False

    assert is_transient_error(err_503) is True
    assert is_transient_error(err_429) is False  # 429 must trigger pause, not infinite backoff
    assert is_transient_error(err_syntax) is False


def test_sqlite_csv_and_json_export(tmp_path):
    """Verify that experiment storage exports genuine CSV and JSON files with all columns."""
    from evaluation.experiment_db import experiment_storage

    csv_out = tmp_path / "test_export.csv"
    json_out = tmp_path / "test_export.json"

    c_ret = experiment_storage.export_to_csv(csv_out)
    j_ret = experiment_storage.export_to_json(json_out)

    assert c_ret.exists()
    assert j_ret.exists()
    assert c_ret.stat().st_size > 0
    assert j_ret.stat().st_size > 0


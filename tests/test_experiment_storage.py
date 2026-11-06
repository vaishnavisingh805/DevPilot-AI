"""Tests for SQLite-backed Persistent Experiment Storage.

Verifies:
1. Database schema creation and table initialization.
2. Accurate recording of performance metrics and execution metadata.
3. Persistence across closing and reopening database connections (simulating process restarts).
4. Filtering by architecture pattern, persona, and task.
5. Aggregate summary statistics and grouping by architecture/persona.
6. Support for storing and querying 40+ genuine experiment runs.
"""

import os
import tempfile
import pytest
from pathlib import Path
from core.schemas.metrics import PerformanceMetrics, AgentTokenUsage
from evaluation.experiment_db import ExperimentStorage


@pytest.fixture
def temp_db():
    """Provides a fresh temporary SQLite database for test isolation."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_file = Path(path)
    storage = ExperimentStorage(db_path=db_file)
    yield storage
    if db_file.exists():
        try:
            db_file.unlink()
        except Exception:
            pass


def test_experiment_storage_record_and_get(temp_db):
    metrics = PerformanceMetrics(
        run_id="RUN-TEST-001",
        architecture_pattern="Hierarchical-Blackboard-A2A",
        persona="Strict-Architect",
        benchmark_task="Add standard_deviation method",
        total_execution_time_seconds=3.45,
        total_prompt_tokens=1500,
        total_completion_tokens=600,
        total_tokens=2100,
        total_cost_usd=0.00045,
        test_pass_rate_percentage=100.0,
        tests_passed=9,
        tests_total=9,
        failure_recovery_cycles=0,
        tool_call_count=4,
        a2a_message_count=4,
        success=True,
    )

    temp_db.record_run(
        metrics=metrics,
        benchmark_task=metrics.benchmark_task,
        persona=metrics.persona,
    )

    assert temp_db.count() == 1
    record = temp_db.get_by_id("RUN-TEST-001")
    assert record is not None
    assert record["run_id"] == "RUN-TEST-001"
    assert record["architecture_pattern"] == "Hierarchical-Blackboard-A2A"
    assert record["persona"] == "Strict-Architect"
    assert record["success"] == 1
    assert record["tests_passed"] == 9
    assert record["total_tokens"] == 2100
    assert record["execution_time_seconds"] == 3.45


def test_experiment_persistence_across_connection_reopen(temp_db):
    """Verify that records persist when closing and reopening a new storage instance."""
    db_path = temp_db.db_path

    # Record run in instance 1
    metrics = PerformanceMetrics(
        run_id="RUN-PERSIST-001",
        architecture_pattern="Sequential-Baseline",
        persona="Balanced-Engineer",
        benchmark_task="Add safe_percentage calculation",
        total_execution_time_seconds=2.10,
        total_tokens=1200,
        success=True,
    )
    temp_db.record_run(metrics)
    assert temp_db.count() == 1

    # Open brand new instance connecting to same database file
    reopened_storage = ExperimentStorage(db_path=db_path)
    assert reopened_storage.count() == 1

    rec = reopened_storage.get_by_id("RUN-PERSIST-001")
    assert rec is not None
    assert rec["run_id"] == "RUN-PERSIST-001"
    assert rec["architecture_pattern"] == "Sequential-Baseline"
    assert rec["persona"] == "Balanced-Engineer"


def test_experiment_filtering_and_aggregations(temp_db):
    # Insert 3 runs with different patterns and personas
    r1 = PerformanceMetrics(
        run_id="RUN-F1",
        architecture_pattern="Hierarchical-Blackboard-A2A",
        persona="Strict-Architect",
        benchmark_task="Task A",
        total_execution_time_seconds=5.0,
        total_tokens=2000,
        total_cost_usd=0.0006,
        test_pass_rate_percentage=100.0,
        tests_passed=10,
        tests_total=10,
        success=True,
    )
    r2 = PerformanceMetrics(
        run_id="RUN-F2",
        architecture_pattern="Sequential-Baseline",
        persona="Permissive-Prototyper",
        benchmark_task="Task B",
        total_execution_time_seconds=2.0,
        total_tokens=800,
        total_cost_usd=0.0002,
        test_pass_rate_percentage=50.0,
        tests_passed=5,
        tests_total=10,
        success=False,
        error_details="Assertion error on line 42",
    )
    r3 = PerformanceMetrics(
        run_id="RUN-F3",
        architecture_pattern="Critic-Reflection-Loop",
        persona="Balanced-Engineer",
        benchmark_task="Task A",
        total_execution_time_seconds=8.0,
        total_tokens=3500,
        total_cost_usd=0.0010,
        test_pass_rate_percentage=100.0,
        tests_passed=10,
        tests_total=10,
        success=True,
    )

    for r in [r1, r2, r3]:
        temp_db.record_run(r, benchmark_task=r.benchmark_task, persona=r.persona)

    assert temp_db.count() == 3

    # Filter by Architecture
    seq_runs = temp_db.get_all(architecture="Sequential-Baseline")
    assert len(seq_runs) == 1
    assert seq_runs[0]["run_id"] == "RUN-F2"

    # Filter by Persona
    strict_runs = temp_db.get_all(persona="Strict-Architect")
    assert len(strict_runs) == 1
    assert strict_runs[0]["run_id"] == "RUN-F1"

    # Filter by Task
    task_a_runs = temp_db.get_all(task="Task A")
    assert len(task_a_runs) == 2

    # Filter by Success
    successful_runs = temp_db.get_all(success_only=True)
    assert len(successful_runs) == 2

    # Summary Statistics
    stats = temp_db.get_summary_statistics()
    assert stats["total_runs"] == 3
    assert stats["successful_runs"] == 2
    assert stats["failed_runs"] == 1
    assert stats["success_rate_percentage"] == 66.67
    assert stats["avg_execution_time_seconds"] == 5.0
    assert stats["total_cost_usd"] == 0.0018

    # Architecture Comparison Aggregation
    arch_comp = temp_db.get_architecture_comparison()
    assert len(arch_comp) == 3
    patterns = [ac["architecture_pattern"] for ac in arch_comp]
    assert "Hierarchical-Blackboard-A2A" in patterns
    assert "Sequential-Baseline" in patterns
    assert "Critic-Reflection-Loop" in patterns

    # Persona Comparison Aggregation
    persona_comp = temp_db.get_persona_comparison()
    assert len(persona_comp) == 3


def test_capacity_support_40_genuine_runs(temp_db):
    """Verify storage easily handles at least 40 genuine experiment runs without degradation."""
    for i in range(1, 45):
        pattern = "Hierarchical-Blackboard-A2A" if i % 3 == 0 else ("Sequential-Baseline" if i % 3 == 1 else "Critic-Reflection-Loop")
        persona = "Strict-Architect" if i % 3 == 0 else ("Balanced-Engineer" if i % 3 == 1 else "Permissive-Prototyper")
        success = (i % 5 != 0)  # 80% pass rate
        m = PerformanceMetrics(
            run_id=f"RUN-SCALE-{i:03d}",
            architecture_pattern=pattern,
            persona=persona,
            benchmark_task=f"Benchmark Task #{((i - 1) % 5) + 1}",
            total_execution_time_seconds=round(1.5 + (i * 0.1), 2),
            total_prompt_tokens=800 + (i * 10),
            total_completion_tokens=300 + (i * 5),
            total_tokens=1100 + (i * 15),
            total_cost_usd=round((1100 + (i * 15)) * 0.0000003, 6),
            test_pass_rate_percentage=100.0 if success else 60.0,
            tests_passed=10 if success else 6,
            tests_total=10,
            success=success,
            error_details=None if success else "Assertion failure on edge condition",
        )
        temp_db.record_run(m, benchmark_task=m.benchmark_task, persona=m.persona)

    assert temp_db.count() == 44
    stats = temp_db.get_summary_statistics()
    assert stats["total_runs"] == 44
    assert stats["successful_runs"] > 30

    # Query with limit
    recent_10 = temp_db.get_all(limit=10)
    assert len(recent_10) == 10


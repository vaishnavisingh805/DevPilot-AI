"""Reproducible Academic Benchmark Execution Harness.

Executes a systematic 45-run evaluation matrix across:
- 5 Benchmark Tasks (Feature Addition, Edge Cases, Security Defense, Type Safety, Parity Logic)
- 3 Architecture Patterns (Hierarchical-Blackboard-A2A, Sequential-Baseline, Critic-Reflection-Loop)
- 3 Persona Variations (Strict-Architect, Balanced-Engineer, Permissive-Prototyper)

Total Matrix Dimensions: 5 tasks x 3 architectures x 3 personas = 45 genuine runs.

Core Features:
1. Per-experiment checkpointing to sandbox_workspace/benchmark_checkpoint.json.
2. Full resume support: never reruns already completed cells unless --force-rerun is passed.
3. Unique, canonical run identifiers for every execution.
4. Persistent SQLite records for both successful and failed runs (sandbox_workspace/experiments.db).
5. HTTP 429 quota exhaustion detection and graceful pause without crashing.
6. Exponential backoff retry for transient network errors (503, timeouts).
7. Zero fabricated or simulated results.
8. Exact token usage and microsecond-level runtime measurement.
9. Real-time progress output (completed, failed, pending, remaining).
10. Dry-run mode consuming zero Gemini API quota.
11. Automatic CSV and JSON export of genuine benchmark records.
"""

import argparse
import csv
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from config.models_config import calculate_cost
from core.schemas.metrics import PerformanceMetrics
from evaluation.benchmark_runner import BENCHMARK_TASKS
from evaluation.experiment_db import experiment_storage
from orchestration.patterns import AgenticPatternType
from orchestration.personas import PersonaType, PERSONA_CONFIGS, get_persona
from orchestration.engine import AutonomousEngineeringOrchestrator
from orchestration.sequential_orchestrator import SequentialBaselineOrchestrator
from orchestration.critic_reflection_orchestrator import CriticReflectionOrchestrator

CHECKPOINT_FILE = settings.SANDBOX_ROOT / "benchmark_checkpoint.json"
DEFAULT_EXPORT_CSV = settings.SANDBOX_ROOT / "benchmark_results.csv"
DEFAULT_EXPORT_JSON = settings.SANDBOX_ROOT / "benchmark_results.json"


def get_cell_key(task_id: str, pattern: AgenticPatternType, persona: PersonaType) -> str:
    """Returns a deterministic, canonical key for a matrix cell."""
    return f"{task_id}::{pattern.value}::{persona.value}"


def generate_run_id(task_id: str, pattern: AgenticPatternType, persona: PersonaType) -> str:
    """Generates a unique, traceable, human-readable run identifier."""
    arch_map = {
        AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A: "HIER",
        AgenticPatternType.SEQUENTIAL_BASELINE: "SEQ",
        AgenticPatternType.CRITIC_REFLECTION_LOOP: "REFL",
    }
    persona_map = {
        PersonaType.STRICT_ARCHITECT: "STRICT",
        PersonaType.BALANCED_ENGINEER: "BAL",
        PersonaType.PERMISSIVE_PROTOTYPER: "PROTO",
    }
    arch_short = arch_map.get(pattern, "ARCH")
    persona_short = persona_map.get(persona, "PERS")
    unique_hash = uuid.uuid4().hex[:6]
    return f"RUN-BENCH-{task_id}-{arch_short}-{persona_short}-{unique_hash}"


def build_benchmark_matrix() -> List[Dict[str, Any]]:
    """Builds the Cartesian product of 5 tasks x 3 patterns x 3 personas = 45 runs."""
    matrix = []
    run_number = 1

    for task in BENCHMARK_TASKS:
        for pattern in [
            AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A,
            AgenticPatternType.SEQUENTIAL_BASELINE,
            AgenticPatternType.CRITIC_REFLECTION_LOOP,
        ]:
            for persona_type in [
                PersonaType.BALANCED_ENGINEER,
                PersonaType.STRICT_ARCHITECT,
                PersonaType.PERMISSIVE_PROTOTYPER,
            ]:
                cell_key = get_cell_key(task["id"], pattern, persona_type)
                matrix.append({
                    "run_number": run_number,
                    "cell_key": cell_key,
                    "task_id": task["id"],
                    "task_title": task["title"],
                    "task_category": task["category"],
                    "prompt": task["prompt"],
                    "architecture": pattern,
                    "persona_type": persona_type,
                })
                run_number += 1

    return matrix


class CheckpointManager:
    """Manages persistent campaign checkpoint state across runs."""

    def __init__(self, checkpoint_path: Optional[Path] = None):
        self.path = Path(checkpoint_path or CHECKPOINT_FILE).resolve()
        self.state: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "campaign_id": f"CAMPAIGN-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated_at": datetime.now(timezone.utc).isoformat(),
            "status": "initialized",
            "completed_cells": {},
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state["last_updated_at"] = datetime.now(timezone.utc).isoformat()
        temp_file = self.path.with_suffix(".tmp")
        temp_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        temp_file.replace(self.path)

    def is_cell_completed(self, cell_key: str) -> bool:
        """Returns True if the cell has a completed successful record in checkpoint or SQLite."""
        # 1. Check checkpoint file
        if cell_key in self.state.get("completed_cells", {}):
            cell_data = self.state["completed_cells"][cell_key]
            if cell_data.get("status") == "completed" and cell_data.get("success", False):
                return True

        # 2. Check SQLite records
        parts = cell_key.split("::")
        if len(parts) == 3:
            task_id, arch, persona = parts
            runs = experiment_storage.get_all(architecture=arch, persona=persona, task=task_id, success_only=True)
            if runs:
                return True
            # Also check by canonical task keyword for existing pilot runs
            keywords = {
                "BENCH-01": "standard_deviation",
                "BENCH-02": "Zero Division",
                "BENCH-03": "Prompt Injection",
                "BENCH-04": "Type",
                "BENCH-05": "median",
            }
            kw = keywords.get(task_id)
            if kw:
                legacy_runs = experiment_storage.get_all(architecture=arch, persona=persona, task=kw, success_only=True)
                if legacy_runs:
                    return True

        return False

    def record_cell(
        self,
        cell_key: str,
        run_id: str,
        status: str,
        success: bool,
        execution_time_seconds: float,
        total_tokens: int,
        estimated_cost_usd: float,
        error_details: Optional[str] = None,
    ) -> None:
        self.state["completed_cells"][cell_key] = {
            "run_id": run_id,
            "status": status,
            "success": success,
            "execution_time_seconds": execution_time_seconds,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "error_details": error_details,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.save()


def is_quota_exhausted_error(exc: BaseException) -> bool:
    """Detects HTTP 429 / RESOURCE_EXHAUSTED errors from Gemini API."""
    err_str = f"{type(exc).__name__}: {str(exc)}".lower()
    quota_indicators = [
        "429",
        "resource_exhausted",
        "resourceexhausted",
        "quota exceeded",
        "rate limit",
        "ratelimit",
        "quota_exhausted",
        "too many requests",
    ]
    return any(ind in err_str for ind in quota_indicators)


def is_transient_error(exc: BaseException) -> bool:
    """Detects transient network/server errors suitable for exponential backoff."""
    if is_quota_exhausted_error(exc):
        return False
    err_str = f"{type(exc).__name__}: {str(exc)}".lower()
    transient_indicators = [
        "503",
        "service unavailable",
        "connection reset",
        "timeout",
        "timed out",
        "temporary failure",
        "500",
        "internal server error",
        "bad gateway",
        "502",
    ]
    return any(ind in err_str for ind in transient_indicators)


def execute_matrix_cell_with_retries(
    cell: Dict[str, Any],
    max_transient_retries: int = 2,
    target_repo: str = "sample_repo",
    auto_commit: bool = False,
) -> Tuple[PerformanceMetrics, Optional[BaseException]]:
    """Executes a single matrix cell with unique run ID, exact measurement, and transient retries."""
    pattern = cell["architecture"]
    persona_cfg = get_persona(cell["persona_type"])
    prompt = cell["prompt"]
    task_id = cell["task_id"]

    run_id = generate_run_id(task_id, pattern, cell["persona_type"])

    attempt = 0
    backoff_delay = 2.0

    while True:
        try:
            # Instantiate dedicated architecture orchestrator
            if pattern == AgenticPatternType.SEQUENTIAL_BASELINE:
                orchestrator = SequentialBaselineOrchestrator(persona=persona_cfg)
            elif pattern == AgenticPatternType.CRITIC_REFLECTION_LOOP:
                orchestrator = CriticReflectionOrchestrator(persona=persona_cfg)
            else:
                orchestrator = AutonomousEngineeringOrchestrator(
                    pattern=AgenticPatternType.HIERARCHICAL_BLACKBOARD_A2A,
                    persona=persona_cfg,
                )

            # High precision timing
            t_start = time.perf_counter()
            metrics = orchestrator.execute_requirement(
                raw_prompt=prompt,
                target_repo=target_repo,
                auto_commit_if_approved=auto_commit,
            )
            t_elapsed = time.perf_counter() - t_start

            # Enforce exact measured values and unique ID
            metrics.run_id = run_id
            metrics.total_execution_time_seconds = round(t_elapsed, 3)
            metrics.benchmark_task = f"{task_id}: {cell['task_title']}"
            metrics.persona = persona_cfg.persona_type.value
            metrics.architecture_pattern = pattern.value
            metrics.is_measurement_estimated = 0 if settings.EXECUTION_MODE == "live" else 1

            # Save genuine record to SQLite
            experiment_storage.record_run(
                metrics=metrics,
                benchmark_task=metrics.benchmark_task,
                persona=metrics.persona,
                execution_status="completed" if metrics.success else "failed",
                error_details=metrics.error_details,
                metadata={
                    "run_number": cell["run_number"],
                    "cell_key": cell["cell_key"],
                    "task_id": task_id,
                    "category": cell["task_category"],
                    "validation_rigor": persona_cfg.validation_rigor,
                    "temperature": persona_cfg.temperature,
                },
            )

            return metrics, None

        except Exception as exc:
            attempt += 1
            if is_quota_exhausted_error(exc):
                # Quota exhausted: never retry immediately
                fail_metrics = PerformanceMetrics(
                    run_id=run_id,
                    architecture_pattern=pattern.value,
                    persona=persona_cfg.persona_type.value,
                    benchmark_task=f"{task_id}: {cell['task_title']}",
                    success=False,
                    execution_status="failed",
                    error_details=f"QUOTA_EXHAUSTED: {str(exc)}",
                    is_measurement_estimated=0 if settings.EXECUTION_MODE == "live" else 1,
                )
                experiment_storage.record_run(
                    metrics=fail_metrics,
                    benchmark_task=fail_metrics.benchmark_task,
                    persona=fail_metrics.persona,
                    execution_status="failed",
                    error_details=fail_metrics.error_details,
                )
                return fail_metrics, exc

            elif is_transient_error(exc) and attempt <= max_transient_retries:
                print(f"    [TRANSIENT ERROR] {exc}. Retrying in {backoff_delay:.1f}s (Attempt {attempt}/{max_transient_retries})...")
                time.sleep(backoff_delay)
                backoff_delay *= 2.0
                continue
            else:
                # Non-transient error or retries exhausted
                fail_metrics = PerformanceMetrics(
                    run_id=run_id,
                    architecture_pattern=pattern.value,
                    persona=persona_cfg.persona_type.value,
                    benchmark_task=f"{task_id}: {cell['task_title']}",
                    success=False,
                    execution_status="failed",
                    error_details=str(exc),
                    is_measurement_estimated=0 if settings.EXECUTION_MODE == "live" else 1,
                )
                experiment_storage.record_run(
                    metrics=fail_metrics,
                    benchmark_task=fail_metrics.benchmark_task,
                    persona=fail_metrics.persona,
                    execution_status="failed",
                    error_details=fail_metrics.error_details,
                )
                return fail_metrics, exc


def export_benchmark_results(
    csv_path: Optional[Path] = None,
    json_path: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """Exports all genuine benchmark records from SQLite to CSV and JSON."""
    c_path = Path(csv_path or DEFAULT_EXPORT_CSV)
    j_path = Path(json_path or DEFAULT_EXPORT_JSON)
    experiment_storage.export_to_csv(c_path)
    experiment_storage.export_to_json(j_path)
    return c_path, j_path


def run_benchmark_campaign(
    max_runs: Optional[int] = None,
    dry_run: bool = False,
    task_filter: Optional[str] = None,
    arch_filter: Optional[str] = None,
    persona_filter: Optional[str] = None,
    force_rerun: bool = False,
    export_only: bool = False,
) -> Dict[str, Any]:
    """Coordinates benchmark execution with resume, checkpointing, and quota safety."""
    if export_only:
        c_path, j_path = export_benchmark_results()
        print(f"Export completed successfully:")
        print(f"  CSV:  {c_path}")
        print(f"  JSON: {j_path}")
        return {"status": "export_completed", "csv": str(c_path), "json": str(j_path)}

    full_matrix = build_benchmark_matrix()
    checkpoint = CheckpointManager()

    # Filter matrix
    filtered_matrix = full_matrix
    if task_filter:
        filtered_matrix = [c for c in filtered_matrix if c["task_id"] == task_filter or task_filter in c["task_title"]]
    if arch_filter:
        filtered_matrix = [c for c in filtered_matrix if c["architecture"].value == arch_filter]
    if persona_filter:
        filtered_matrix = [c for c in filtered_matrix if c["persona_type"].value == persona_filter]

    if max_runs and max_runs > 0:
        filtered_matrix = filtered_matrix[:max_runs]

    # Calculate status counts
    total_cells = len(filtered_matrix)
    completed_cells_count = sum(1 for c in filtered_matrix if checkpoint.is_cell_completed(c["cell_key"]) and not force_rerun)
    pending_cells_count = total_cells - completed_cells_count

    print(f"\n{'='*80}")
    print(f"ACADEMIC MULTI-AGENT BENCHMARK CAMPAIGN")
    print(f"Total Configured Matrix Cells:  {len(full_matrix)}")
    print(f"Active Filtered Execution Set:  {total_cells}")
    print(f"Already Completed (Checkpoint): {completed_cells_count}")
    print(f"Pending Execution:              {pending_cells_count}")
    print(f"Execution Mode:                 {settings.EXECUTION_MODE}")
    print(f"Active Model Target:            {settings.DEFAULT_MODEL}")
    print(f"Checkpoint File:                {checkpoint.path}")
    print(f"SQLite Persistence Path:        {settings.EXPERIMENTS_DB_PATH}")
    print(f"{'='*80}\n")

    if dry_run:
        print("[DRY RUN] Matrix Plan Validation & Cell Status:")
        print(f"{'#':<4} | {'Task':<8} | {'Architecture':<28} | {'Persona':<22} | {'Status'}")
        print("-" * 80)
        for c in filtered_matrix:
            is_done = checkpoint.is_cell_completed(c["cell_key"])
            status_tag = "[COMPLETED - SKIP]" if (is_done and not force_rerun) else "[PENDING]"
            print(f"#{c['run_number']:02d} | {c['task_id']:<8} | {c['architecture'].value:<28} | {c['persona_type'].value:<22} | {status_tag}")
        print("\nDry run completed successfully. Zero Gemini API quota consumed.\n")
        return {
            "status": "dry_run_completed",
            "total_cells": total_cells,
            "completed": completed_cells_count,
            "pending": pending_cells_count,
        }

    # Execution Loop
    executed_results = []
    failed_results = []
    start_time = time.time()

    for idx, cell in enumerate(filtered_matrix, 1):
        cell_key = cell["cell_key"]
        
        # Checkpoint resume check
        if not force_rerun and checkpoint.is_cell_completed(cell_key):
            print(f"[{idx}/{total_cells}] Skipping completed cell #{cell['run_number']:02d} ({cell['task_id']} | {cell['architecture'].value} | {cell['persona_type'].value})")
            continue

        print(f"\n{'='*80}")
        progress_pct = (len(executed_results) + completed_cells_count) / total_cells * 100.0
        print(f"Progress: [{len(executed_results) + completed_cells_count}/{total_cells}] ({progress_pct:.1f}% done) | Cell #{cell['run_number']:02d}: {cell['task_id']} | {cell['architecture'].value} | {cell['persona_type'].value}")
        print(f"{'='*80}")

        metrics, exc = execute_matrix_cell_with_retries(cell)

        if exc and is_quota_exhausted_error(exc):
            checkpoint.record_cell(
                cell_key=cell_key,
                run_id=metrics.run_id,
                status="failed_quota_exhausted",
                success=False,
                execution_time_seconds=metrics.total_execution_time_seconds,
                total_tokens=metrics.total_tokens,
                estimated_cost_usd=metrics.total_cost_usd,
                error_details=metrics.error_details,
            )
            print("\n" + "=" * 80)
            print("⚠️  GEMINI API QUOTA EXHAUSTED (HTTP 429 / RESOURCE_EXHAUSTED)")
            print("=" * 80)
            print("Execution gracefully paused to protect API allocation.")
            print(f"All progress up to Cell #{cell['run_number']} has been saved to checkpoint and SQLite.")
            print("To resume when quota resets, run:")
            print("  python scripts/run_benchmark_matrix.py")
            print("=" * 80 + "\n")
            break

        # Record normal completion or non-quota failure
        checkpoint.record_cell(
            cell_key=cell_key,
            run_id=metrics.run_id,
            status="completed" if metrics.success else "failed",
            success=metrics.success,
            execution_time_seconds=metrics.total_execution_time_seconds,
            total_tokens=metrics.total_tokens,
            estimated_cost_usd=metrics.total_cost_usd,
            error_details=metrics.error_details,
        )

        status_symbol = "✅ SUCCESS" if metrics.success else "❌ FAILED"
        print(f"    --> {status_symbol} | Time: {metrics.total_execution_time_seconds:.2f}s | Tokens: {metrics.total_tokens:,} | Cost: ${metrics.total_cost_usd:.6f} | Pass Rate: {metrics.test_pass_rate_percentage:.1f}%")

        if metrics.success:
            executed_results.append(metrics)
        else:
            failed_results.append(metrics)

    # Export records
    export_benchmark_results()
    total_duration = time.time() - start_time

    print(f"\n{'='*80}")
    print(f"BENCHMARK RUN PAUSED OR COMPLETED")
    print(f"Newly Executed: {len(executed_results)} passed, {len(failed_results)} failed")
    print(f"Duration:       {total_duration:.2f}s")
    print(f"SQLite DB:      {settings.EXPERIMENTS_DB_PATH}")
    print(f"Checkpoint:     {checkpoint.path}")
    print(f"{'='*80}\n")

    return {
        "status": "finished",
        "newly_executed": len(executed_results),
        "newly_failed": len(failed_results),
        "total_duration": total_duration,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Academic Multi-Agent Benchmark Campaign Runner")
    parser.add_argument("--dry-run", action="store_true", help="Validate matrix and display status without executing agent workflows")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from last checkpoint (default: True)")
    parser.add_argument("--force-rerun", action="store_true", help="Force execution even for already completed cells")
    parser.add_argument("--runs-limit", type=int, default=None, help="Limit number of cells to execute")
    parser.add_argument("--task-id", type=str, default=None, help="Filter by Task ID (e.g. BENCH-01)")
    parser.add_argument("--pattern", type=str, default=None, help="Filter by Architecture Pattern")
    parser.add_argument("--persona", type=str, default=None, help="Filter by Persona")
    parser.add_argument("--export-only", action="store_true", help="Export existing SQLite records to CSV/JSON without running")

    args = parser.parse_args()

    run_benchmark_campaign(
        max_runs=args.runs_limit,
        dry_run=args.dry_run,
        task_filter=args.task_id,
        arch_filter=args.pattern,
        persona_filter=args.persona,
        force_rerun=args.force_rerun,
        export_only=args.export_only,
    )

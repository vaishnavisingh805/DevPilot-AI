"""Metrics Collector and Historical Run Aggregator.

Backed by persistent SQLite storage (`evaluation.experiment_db.ExperimentStorage`),
maintaining historical run integrity across process restarts.
"""

from typing import List, Dict, Any, Optional
from core.schemas import PerformanceMetrics
from evaluation.experiment_db import experiment_storage, ExperimentStorage


class MetricsCollector:
    """Stores and aggregates historical execution performance metrics via SQLite."""

    def __init__(self, storage: Optional[ExperimentStorage] = None):
        self.storage = storage or experiment_storage
        self._in_memory_cache: List[PerformanceMetrics] = []

    def record_run(
        self,
        metrics: PerformanceMetrics,
        benchmark_task: Optional[str] = None,
        persona: Optional[str] = None,
        error_details: Optional[str] = None,
    ) -> None:
        """Records an execution both in-memory and persistently in SQLite."""
        self._in_memory_cache.append(metrics)
        self.storage.record_run(
            metrics=metrics,
            benchmark_task=benchmark_task,
            persona=persona,
            execution_status="completed" if metrics.success else "failed",
            error_details=error_details or metrics.error_details,
        )

    def get_history(self) -> List[PerformanceMetrics]:
        """Returns in-memory cache, reloading from SQLite if memory is empty."""
        if not self._in_memory_cache and self.storage.count() > 0:
            records = self.storage.get_all()
            for r in records:
                try:
                    pm = PerformanceMetrics(
                        run_id=r["run_id"],
                        architecture_pattern=r["architecture_pattern"],
                        persona=r["persona"],
                        benchmark_task=r["benchmark_task"],
                        total_execution_time_seconds=r["execution_time_seconds"],
                        total_prompt_tokens=r["prompt_tokens"],
                        total_completion_tokens=r["completion_tokens"],
                        total_tokens=r["total_tokens"],
                        total_cost_usd=r["estimated_cost_usd"],
                        test_pass_rate_percentage=r["test_pass_rate"],
                        tests_passed=r["tests_passed"],
                        tests_total=r["tests_total"],
                        failure_recovery_cycles=r["failure_recovery_cycles"],
                        tool_call_count=r["tool_call_count"],
                        a2a_message_count=r["a2a_message_count"],
                        success=bool(r["success"]),
                        error_details=r["error_details"],
                        model_name=r["model_name"],
                        is_measurement_estimated=bool(r["is_measurement_estimated"]),
                    )
                    self._in_memory_cache.append(pm)
                except Exception:
                    pass
        return list(self._in_memory_cache)

    def get_summary_statistics(self) -> Dict[str, Any]:
        """Returns SQLite aggregate statistics."""
        return self.storage.get_summary_statistics()

    def get_architecture_comparison(self) -> List[Dict[str, Any]]:
        return self.storage.get_architecture_comparison()

    def get_persona_comparison(self) -> List[Dict[str, Any]]:
        return self.storage.get_persona_comparison()

    def clear(self) -> None:
        self._in_memory_cache.clear()
        self.storage.clear()


# Global Singleton
metrics_collector = MetricsCollector()

"""Pydantic schemas for Performance Evaluation and Metrics."""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class AgentTokenUsage(BaseModel):
    """Token consumption per agent/framework."""
    agent_id: str
    framework: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class PerformanceMetrics(BaseModel):
    """Aggregate run metrics for evaluation and dashboard telemetry."""
    run_id: str = Field(default_factory=lambda: f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    sandbox_run_id: Optional[str] = None
    sandbox_path: Optional[str] = None
    architecture_pattern: str = Field(default="Hierarchical-Blackboard-A2A")
    persona: str = Field(default="Balanced-Engineer")
    benchmark_task: str = Field(default="")
    total_execution_time_seconds: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    test_pass_rate_percentage: float = 0.0
    tests_passed: int = 0
    tests_total: int = 0
    failure_recovery_cycles: int = 0
    tool_call_count: int = 0
    a2a_message_count: int = 0
    agent_breakdowns: List[AgentTokenUsage] = Field(default_factory=list)
    success: bool = False
    error_details: Optional[str] = None
    model_name: str = Field(default="gemini-3.8-flash")
    is_measurement_estimated: bool = False
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


"""Pydantic schemas for Unit Testing and Verification Results."""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class TestResultItem(BaseModel):
    """Result of an individual test case."""
    __test__ = False
    test_node_id: str = Field(..., description="e.g. tests/test_calculator.py::test_power")
    outcome: str = Field(..., description="'passed', 'failed', 'error', 'skipped'")
    duration_seconds: float = Field(default=0.0)
    failure_message: Optional[str] = Field(default=None, description="Assertion error or stack trace if failed")


class TestResultReport(BaseModel):
    """Comprehensive test execution report emitted by the MCP Test Runner tool."""
    __test__ = False
    report_id: str = Field(default_factory=lambda: f"TEST-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    all_passed: bool = False
    execution_time_seconds: float = 0.0
    items: List[TestResultItem] = Field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

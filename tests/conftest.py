"""Pytest configuration and global fixtures for multi-agent test isolation."""

from pathlib import Path
import pytest
from config.settings import settings

CANONICAL_CALCULATOR_CODE = '''"""Advanced Calculator Module for DevPilot AI Baseline Testing."""

import math
from typing import List, Union


class AdvancedCalculator:
    """Mathematical calculations engine."""

    def add(self, a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
        """Adds two numbers."""
        return a + b

    def subtract(self, a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
        """Subtracts b from a."""
        return a - b

    def multiply(self, a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
        """Multiplies two numbers."""
        return a * b

    def divide(self, a: Union[int, float], b: Union[int, float]) -> float:
        """Divides a by b. Raises ZeroDivisionError if b is 0."""
        if b == 0:
            raise ZeroDivisionError("Division by zero is not permitted.")
        return a / b

    def mean(self, numbers: List[Union[int, float]]) -> float:
        """Calculates arithmetic mean of a non-empty list."""
        if not numbers:
            raise ValueError("Input list cannot be empty.")
        return sum(numbers) / len(numbers)
'''


@pytest.fixture(autouse=True)
def preserve_sample_repo():
    """Ensures sandbox_workspace/sample_repo/src/calculator.py is preserved across all test runs."""
    calc_path = settings.SANDBOX_ROOT / "sample_repo" / "src" / "calculator.py"
    if calc_path.parent.exists():
        calc_path.write_text(CANONICAL_CALCULATOR_CODE, encoding="utf-8")
    yield
    if calc_path.parent.exists():
        calc_path.write_text(CANONICAL_CALCULATOR_CODE, encoding="utf-8")
    ext_path = settings.SANDBOX_ROOT / "sample_repo" / "src" / "extension.py"
    if ext_path.exists():
        try:
            ext_path.unlink()
        except Exception:
            pass


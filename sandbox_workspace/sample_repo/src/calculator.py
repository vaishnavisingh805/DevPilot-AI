"""Advanced Calculator Module for DevPilot AI Baseline Testing."""

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

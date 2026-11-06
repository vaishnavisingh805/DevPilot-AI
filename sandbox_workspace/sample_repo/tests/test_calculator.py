"""Unit tests for AdvancedCalculator."""

import pytest
from src.calculator import AdvancedCalculator


@pytest.fixture
def calc():
    return AdvancedCalculator()


def test_add(calc):
    assert calc.add(2, 3) == 5
    assert calc.add(-1, 1) == 0


def test_subtract(calc):
    assert calc.subtract(10, 4) == 6


def test_multiply(calc):
    assert calc.multiply(3, 7) == 21


def test_divide(calc):
    assert calc.divide(10, 2) == 5
    with pytest.raises(ZeroDivisionError):
        calc.divide(5, 0)


def test_mean(calc):
    assert calc.mean([1, 2, 3, 4, 5]) == 3.0
    with pytest.raises(ValueError):
        calc.mean([])


"""Tests for demo_pkg utility functions."""

import pytest

from demo_pkg.utils import add, greet


class TestAdd:
    """Tests for the add function."""

    def test_add_two_positive_numbers(self) -> None:
        """Return the sum of two positive integers."""
        assert add(3, 5) == 8

    def test_add_positive_and_negative(self) -> None:
        """Return the correct result when mixing signs."""
        assert add(10, -3) == 7

    def test_add_zero(self) -> None:
        """Return the same number when adding zero."""
        assert add(0, 7) == 7
        assert add(7, 0) == 7

    def test_add_two_negative_numbers(self) -> None:
        """Return the sum of two negative integers."""
        assert add(-4, -6) == -10


class TestGreet:
    """Tests for the greet function."""

    def test_greet_returns_formatted_string(self) -> None:
        """Return a greeting with the given name."""
        result = greet("Alice")
        assert result == "Hello, Alice!"

    def test_greet_with_empty_string(self) -> None:
        """Handle an empty name gracefully."""
        result = greet("")
        assert result == "Hello, !"

    def test_greet_is_string(self) -> None:
        """Return a value of type str."""
        assert isinstance(greet("Bob"), str)

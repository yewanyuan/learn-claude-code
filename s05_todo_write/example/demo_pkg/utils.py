"""Utility functions for demo_pkg."""


def add(a: int, b: int) -> int:
    """Return the sum of two integers.

    Args:
        a: The first integer.
        b: The second integer.

    Returns:
        The sum of a and b.
    """
    return a + b


def greet(name: str) -> str:
    """Return a greeting string for the given name.

    Args:
        name: The name of the person to greet.

    Returns:
        A formatted greeting string.
    """
    return f"Hello, {name}!"

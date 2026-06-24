"""A simple greeting module."""


def greet(name: str) -> None:
    """Print a greeting message for the given name.

    Args:
        name: The name of the person to greet.
    """
    message = f"Hello, {name}"
    print(message)


def main() -> None:
    """Run the main greeting example."""
    greet("Claude")


if __name__ == "__main__":
    main()

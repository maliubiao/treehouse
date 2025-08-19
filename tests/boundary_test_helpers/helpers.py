"""
Helper functions for testing boundary calls.
These functions are intended to be *non-targets* for tracing.
"""


def non_target_helper(a: int, b: int) -> int:
    """This function is NOT a target for tracing."""
    # This line should NOT be traced.
    result = a - b
    return result


def non_target_raiser() -> None:
    """A non-target function that raises an exception."""
    # This line should NOT be traced.
    raise ValueError("Error from non-target function")

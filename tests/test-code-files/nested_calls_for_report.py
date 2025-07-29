# -*- coding: utf-8 -*-
"""
A simple script with nested function calls to generate a trace report for E2E testing.
"""


def c() -> None:
    """Innermost function."""
    x: int = 30
    print(f"Inside c, x = {x}")


def b() -> None:
    """Middle function, calls c."""
    y: int = 20
    print(f"Inside b, y = {y}")
    c()
    print("Leaving b")


def a() -> None:
    """Outermost function, calls b."""
    z: int = 10
    print(f"Inside a, z = {z}")
    b()
    print("Leaving a")


if __name__ == "__main__":
    a()

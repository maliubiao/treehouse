from dataclasses import dataclass
from enum import Enum


class TestStatus(Enum):
    """Enumeration for test execution status."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class TestResult:
    """Data class to hold the result of a single test execution."""

    name: str
    status: TestStatus
    duration: float
    message: str = ""

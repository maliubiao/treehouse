import re
from typing import List, TypedDict


class CoverageTestPlan:
    r"""A strongly-typed parser for test plan format validation and processing."""

    class TestCase(TypedDict):
        class_name: str
        test_methods: List["CoverageTestPlan.TestMethod"]

    class TestMethod(TypedDict):
        name: str
        description: str

    TEST_CASE_PATTERN = re.compile(
        r"\[test case start\](.*?)\[test case end\]", re.DOTALL
    )
    CLASS_NAME_PATTERN = re.compile(r"\[class name start\](.*?)\[class name end\]")
    METHOD_PATTERN = re.compile(
        r'def (test_\w+)\(.*?\):(?:\s*"""(.*?)"""|\s*(?:[^"]|"[^"]|""[^"])*?(?=\s*def|\s*class|\Z))',
        re.DOTALL,
    )

    @classmethod
    def parse_test_plan(cls, plan_content: str) -> List[TestCase]:
        """Parse the test plan content into structured data.

        Args:
            plan_content: The raw test plan content string

        Returns:
            List of parsed test cases with their methods
        """
        test_cases = []

        for case_match in cls.TEST_CASE_PATTERN.finditer(plan_content):
            case_content = case_match.group(1)

            # Extract class name
            class_name_match = cls.CLASS_NAME_PATTERN.search(case_content)
            if not class_name_match:
                continue
            class_name = class_name_match.group(1).strip()

            # Extract test methods
            methods = []
            for method_match in cls.METHOD_PATTERN.finditer(case_content):
                if not method_match.group(2):
                    continue
                methods.append(
                    cls.TestMethod(
                        name=method_match.group(1),
                        description=method_match.group(2).strip(),
                    )
                )

            test_cases.append(cls.TestCase(class_name=class_name, test_methods=methods))

        return test_cases

    @classmethod
    def validate_test_plan(cls, plan_content: str) -> bool:
        """Validate the test plan format is correct.

        Args:
            plan_content: The raw test plan content string

        Returns:
            True if the format is valid, False otherwise
        """
        try:
            cases = cls.parse_test_plan(plan_content)
            return len(cases) > 0
        except Exception:
            return False

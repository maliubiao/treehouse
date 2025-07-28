# pylint: skip-file
from typing import List, Optional, Sequence


class MyType:
    pass


def example(
    a: int,
    b: MyType,
    c: List[MyType],
    d: Optional[List[int]],
    e: "Optional[MyType]",
    f: dict[str, MyType],
    g: tuple[MyType, int],
    h: Sequence[MyType],
):
    pass

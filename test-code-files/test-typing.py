from typing import List, Optional

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
    h: typing.Sequence[MyType]
):
    pass

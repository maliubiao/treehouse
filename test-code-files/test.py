# pylint: disable=undefined-variable,unnecessary-pass,unnecessary-comprehension,raise-missing-from,keyword-arg-before-vararg,redefined-outer-name,unspecified-encoding

import os
import sys
import sys as sys1

print(os.listdir("."))


def n(arg):
    def decorator(func):
        return func

    return decorator


def decorator1(func):
    return func


def decorator2(arg):
    def decorator(func):
        return func

    return decorator


def b():
    sys.exit(0)


class SomeAsyncObj:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args, **kwargs):
        pass


class AsyncIter:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


async_iter = AsyncIter()


class C:
    def a(self):
        """hello"""
        b()

    @n(1)
    def d(self):
        self.e()
        self.z()

    def e(self):
        return 1

    async def f(self):
        pass

    def z(self):
        """aaa"""

    @staticmethod
    def static_m():
        print("static")

    @classmethod
    def class_m(cls):
        def inner_func():
            return list(range(5))

        return inner_func()

    async def async_with_example(self):
        async with SomeAsyncObj() as obj:
            yield obj


def f():
    pass


@n(1)
@n(2)
async def f3():
    pass


def f1():
    pass


def annotated_func(a: int, b: str = "test") -> bool:
    """Docstring with triple quotes"""
    if a > 0:
        return b.isdigit()
    return False


def gen_func():
    yield 1
    yield from [2, 3]


def default_args(a, *args, b=1, **kwargs):
    try:
        return a + b + sum(args) + sum(kwargs.values())
    except TypeError as exc:
        raise ValueError("Invalid arguments") from exc


@decorator1
@decorator2(arg=2)
def multi_deco():
    def lambda_func(x):
        return x**2

    return lambda_func(5)


def nested_scope():
    def level1():
        var = [x * 2 for x in range(10) if x % 2 == 0]

        def level2():
            return var + [True, False]

        return level2()

    return level1()


async def async_for_example():
    async for item in async_iter:
        with open(item, encoding="utf-8") as file:
            content = file.read()
            print(content.splitlines())


if __name__ == "__main__":
    pass

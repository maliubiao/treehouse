import time

from debugger import tracer

a = 1

x = 1


def e():
    pass


s = set()


class TestClass:
    def instance_method(self):
        return "instance"

    @staticmethod
    def static_method():
        return "static"


def gen_func():
    yield 1
    yield 2


def func_args(a, b=2):
    return a + b


def nested_call():
    func_args(1)
    TestClass.static_method()


def raise_again():
    try:
        raise ValueError("again")
    except ValueError as e:
        raise RuntimeError("wrapped") from e


def exc(x):
    if x == 1:
        raise ValueError("1")
    elif x == 3:
        nested_call()
    else:
        return x


def handle_exceptions():
    try:
        exc(1)
    except ValueError:
        pass

    try:
        raise_again()
    except RuntimeError:
        pass

    try:
        next(iter([]))
    except StopIteration:
        pass

    # New complex exception handling cases
    try:
        # Case 1: Handle exception then raise new type
        raise ValueError("initial error")
    except ValueError as e:
        print("Handling ValueError, performing calculations")
        result = 10 + 5
        s.add(result)
        raise RuntimeError("New error after handling") from e

    try:
        # Case 2: Handle and re-raise with modification
        next(iter([]))
    except StopIteration as e:
        print("Handling StopIteration, modifying state")
        global x
        x += 10
        raise KeyError("KeyError after cleanup") from e

    try:
        # Case 3: Nested handling and re-raise
        func_args(1, "invalid")  # TypeError
    except TypeError as e:
        print("Handling TypeError, executing valid code")
        TestClass.static_method()
        raise ValueError("Final error") from e


def c(u=2):
    t = tracer.start_trace(config=tracer.TraceConfig(target_files=["*.py"], enable_var_trace=True, trace_c_calls=True))
    try:
        e()
        for i in range(3):
            if i % 2 == 0:
                print("even")
            else:
                print("odd")
            s.add(i)

        g = gen_func()
        for i in g:
            print(i)
        func_args(1)
        func_args(1, 3)

        obj = TestClass()
        obj.instance_method()
        TestClass.static_method()

        # handle_exceptions()
        nested_call()

        # Add a generator expression similar to the log to observe its trace behavior
        _ = any(item > 0 for item in [1, 2, 3, 4])  # This creates a <genexpr>

        [i for i in range(3)]
        {i: i for i in range(2)}

        exc(3)
        exc(2)

    finally:
        tracer.stop_trace(t)


if __name__ == "__main__":
    while True:
        c()
        time.sleep(1)

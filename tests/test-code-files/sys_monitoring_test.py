#!/usr/bin/env python3
"""
Complex async function for testing Python sys.monitoring tracing system.
This demonstrates various async patterns, exception handling, and generator functions.
"""

import asyncio
import sys
import time
from typing import AsyncGenerator, List, Optional


class MonitoringTracer:
    """Setup sys.monitoring tracing for async functions"""

    def __init__(self):
        self.events = []
        self.tool_id = 1

    def start_tracing(self):
        """Enable monitoring for all event types"""
        sys.monitoring.use_tool_id(self.tool_id, "async_tracer")

        # Enable all event types
        events_to_trace = [
            sys.monitoring.events.PY_START,
            sys.monitoring.events.PY_RETURN,
            sys.monitoring.events.PY_UNWIND,
            sys.monitoring.events.LINE,
            sys.monitoring.events.RAISE,
            sys.monitoring.events.EXCEPTION_HANDLED,
            sys.monitoring.events.PY_YIELD,
        ]

        for event in events_to_trace:
            sys.monitoring.set_events(self.tool_id, event)

        # Set event handlers
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.PY_START, self.on_py_start)
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.PY_RETURN, self.on_py_return)
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.PY_UNWIND, self.on_py_unwind)
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.LINE, self.on_line)
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.RAISE, self.on_raise)
        sys.monitoring.register_callback(
            self.tool_id, sys.monitoring.events.EXCEPTION_HANDLED, self.on_exception_handled
        )
        sys.monitoring.register_callback(self.tool_id, sys.monitoring.events.PY_YIELD, self.on_yield)

    def stop_tracing(self):
        """Disable monitoring"""
        sys.monitoring.set_events(self.tool_id, 0)

    def on_py_start(self, code, instruction_ptr):
        self.events.append(f"PY_START: {code.co_name} at line {code.co_firstlineno}")

    def on_py_return(self, code, instruction_ptr, retval):
        self.events.append(f"PY_RETURN: {code.co_name}")

    def on_py_unwind(self, code, instruction_ptr):
        self.events.append(f"PY_UNWIND: {code.co_name}")

    def on_line(self, code, line_number):
        self.events.append(f"LINE: {code.co_name}:{line_number}")

    def on_raise(self, code, instruction_ptr, exc):
        self.events.append(f"RAISE: {code.co_name} - {type(exc).__name__}: {exc}")

    def on_exception_handled(self, code, instruction_ptr, exc):
        self.events.append(f"EXCEPTION_HANDLED: {code.co_name} - {type(exc).__name__}")

    def on_yield(self, code, instruction_ptr, value):
        self.events.append(f"YIELD: {code.co_name}")

    def print_events(self):
        """Print all captured events"""
        for i, event in enumerate(self.events, 1):
            print(f"{i:3d}: {event}")


async def complex_async_operation(data: List[int]) -> float:
    """Main complex async function with multiple await points and error handling"""

    if not data:
        raise ValueError("Empty data list provided")

    # First await - simple delay
    await asyncio.sleep(0.01)

    try:
        # Process data in chunks with nested async calls
        results = []
        for chunk in [data[i : i + 3] for i in range(0, len(data), 3)]:
            result = await process_chunk(chunk)
            results.append(result)

            # Conditional await based on result
            if result > 50:
                await asyncio.sleep(0.005)

        # Use async generator
        final_result = 0.0
        async for value in async_result_generator(results):
            final_result += value

            # Another await with different timing
            if final_result > 100:
                await asyncio.sleep(0.002)

        return final_result / len(results) if results else 0.0

    except ValueError as e:
        print(f"ValueError caught: {e}")
        # Re-raise with different exception type
        raise RuntimeError(f"Processing failed: {e}") from e

    except Exception as e:
        # This will demonstrate exception handling events
        print(f"Unexpected error: {e}")
        await asyncio.sleep(0.001)  # await in exception handler
        raise


async def process_chunk(chunk: List[int]) -> float:
    """Process a chunk of data with potential errors"""

    if any(x < 0 for x in chunk):
        raise ValueError("Negative values not allowed")

    # Simulate some async work
    await asyncio.sleep(0.003)

    # Complex calculation with conditional awaits
    total = sum(chunk)

    if total > 100:
        await asyncio.sleep(0.004)  # Extra processing time for large values

    # Nested async call
    adjusted = await adjust_value(total, len(chunk))

    return adjusted


async def adjust_value(value: int, factor: int) -> float:
    """Adjust value with async operation"""

    await asyncio.sleep(0.002)

    if factor == 0:
        # This will cause division by zero
        return value / factor

    # Complex adjustment with multiple awaits
    result = value / factor

    if result > 25:
        await asyncio.sleep(0.001)
        result = await apply_discount(result)

    return result


async def apply_discount(value: float) -> float:
    """Apply discount with potential error"""

    await asyncio.sleep(0.0015)

    if value > 100:
        # Simulate API call that might fail
        raise ConnectionError("Discount service unavailable")

    return value * 0.9


async def async_result_generator(results: List[float]) -> AsyncGenerator[float, None]:
    """Async generator that yields processed results"""

    for i, result in enumerate(results):
        # Yield with await
        await asyncio.sleep(0.0005)

        # Transform result
        transformed = result * (1 + i * 0.1)

        # Conditional await in generator
        if transformed > 75:
            await asyncio.sleep(0.0008)

        yield transformed

        # Another await after yield
        await asyncio.sleep(0.0003)


async def deep_stack_operation_a(id: int, depth: int = 0) -> float:
    """Coroutine with deep call stack for testing concurrent tracing"""
    if depth >= 3:
        # Base case - do some async work
        await asyncio.sleep(0.01 + id * 0.002)
        return id * 10.0 + depth

    # Recursive call to create deep stack
    result = await deep_stack_operation_a(id, depth + 1)
    await asyncio.sleep(0.005)

    # More async operations in the stack
    intermediate = await process_intermediate_result(result, id)
    await asyncio.sleep(0.003)

    return intermediate * 1.1


async def deep_stack_operation_b(id: int, depth: int = 0) -> str:
    """Another coroutine with different deep stack pattern"""
    if depth >= 3:
        await asyncio.sleep(0.008 + id * 0.001)
        return f"result_{id}_{depth}"

    # Different async pattern with conditional awaits
    if depth % 2 == 0:
        await asyncio.sleep(0.004)
    else:
        await asyncio.sleep(0.006)

    next_result = await deep_stack_operation_b(id, depth + 1)

    # Process with more async calls
    processed = await transform_string_result(next_result, id)
    await asyncio.sleep(0.002)

    return f"processed_{processed}"


async def process_intermediate_result(value: float, id: int) -> float:
    """Intermediate processing with async operations"""
    await asyncio.sleep(0.003)

    # Complex calculation with conditional await
    if value > 50:
        await asyncio.sleep(0.002)
        return value * 0.8
    else:
        await asyncio.sleep(0.001)
        return value * 1.2


async def transform_string_result(value: str, id: int) -> str:
    """String transformation with async operations"""
    await asyncio.sleep(0.002)

    # Simulate string processing with awaits
    parts = value.split("_")

    if len(parts) > 1:
        await asyncio.sleep(0.001)
        return f"{parts[-1]}_{id}"

    await asyncio.sleep(0.0015)
    return f"transformed_{value}"


async def run_concurrent_coroutines() -> List[str]:
    """Launch multiple concurrent coroutines with deep stacks"""

    # Create multiple coroutines with different stack depths
    coroutines = [deep_stack_operation_a(i) for i in range(3)] + [deep_stack_operation_b(i + 3) for i in range(2)]

    # Run all coroutines concurrently
    results = await asyncio.gather(*coroutines, return_exceptions=True)

    # Format results for output
    formatted_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            formatted_results.append(f"Coroutine {i} failed: {result}")
        else:
            formatted_results.append(f"Coroutine {i} result: {result}")

    return formatted_results


async def main():
    """Main function to run the complex async operation"""

    # Setup monitoring
    # tracer = MonitoringTracer()
    # tracer.start_tracing()

    try:
        print("=== Testing Complex Async Operations ===")
        # Test data with various scenarios
        test_data = [
            [10, 20, 30, 40, 50],  # Normal case
            [5, 15, 25, 35],  # Smaller set
            [100, 200, 300],  # Large values
            [1, 2, 3, -4, 5],  # Contains negative (will cause ValueError)
            [0, 0, 0],  # Zero values
        ]

        for i, data in enumerate(test_data):
            print(f"\n=== Test Case {i + 1}: {data} ===")

            try:
                result = await complex_async_operation(data)
                print(f"Result: {result:.2f}")

            except Exception as e:
                print(f"Error in test case {i + 1}: {type(e).__name__}: {e}")

            # Small delay between test cases
            await asyncio.sleep(0.1)

        print("\n" + "=" * 60)
        print("=== Testing Concurrent Coroutines with Deep Stacks ===")
        print("=" * 60)

        # Run concurrent coroutines with deep stacks
        concurrent_results = await run_concurrent_coroutines()
        for result in concurrent_results:
            print(result)

    finally:
        #    tracer.stop_tracing()

        print("\n" + "=" * 60)
        print("MONITORING EVENTS CAPTURED:")
        print("=" * 60)
        # tracer.print_events()


if __name__ == "__main__":
    asyncio.run(main())

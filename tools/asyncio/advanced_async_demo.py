import asyncio
import concurrent.futures  # For run_coroutine_threadsafe's Future and TimeoutError
import contextvars  # Used implicitly by asyncio for context propagation
import datetime
import random
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Set to store background tasks to prevent them from being garbage collected.
# asyncio only keeps weak references to tasks created with create_task.
background_tasks: Set[asyncio.Task[Any]] = set()


async def simulate_io_task(name: str, duration: float, will_fail: bool = False) -> str:
    """
    Simulates an I/O-bound task with a given duration.
    Can optionally raise an exception.
    """
    start_time = time.time()
    current_task: Optional[asyncio.Task[Any]] = asyncio.current_task()
    # Use task name if available, otherwise fallback to provided name
    task_display_name: str = current_task.get_name() if current_task and current_task.get_name() else name
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Task '{task_display_name}': Starting {name} for {duration:.2f}s..."
    )

    try:
        await asyncio.sleep(duration)
        if will_fail:
            raise ValueError(f"Simulated failure in {name}")
    except asyncio.CancelledError:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Task '{task_display_name}': {name} was cancelled after {time.time() - start_time:.2f}s."
        )
        raise
    except Exception as e:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Task '{task_display_name}': {name} failed with {e!r} after {time.time() - start_time:.2f}s."
        )
        raise
    finally:
        # This block executes whether the task completes, cancels, or fails.
        # Check task.done() before accessing result/exception/cancelled status to be safe.
        if current_task and current_task.done():
            if current_task.cancelled():
                # Already handled by the except asyncio.CancelledError block, but for completeness.
                pass  # print message already happened
            elif current_task.exception():
                # Already handled by the except Exception block, but for completeness.
                pass  # print message already happened
            else:
                # Task completed normally without cancellation or exception.
                print(
                    f"[{datetime.datetime.now().strftime('%X')}] Task '{task_display_name}': {name} completed normally after {time.time() - start_time:.2f}s."
                )
    return f"Result of {name}"


def simulate_blocking_call(name: str, duration: float) -> str:
    """
    Simulates a CPU-bound or blocking I/O operation.
    """
    start_time = time.time()
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Thread '{threading.current_thread().name}': Starting blocking call {name} for {duration:.2f}s..."
    )
    time.sleep(duration)
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Thread '{threading.current_thread().name}': Blocking call {name} completed after {time.time() - start_time:.2f}s."
    )
    return f"Result from blocking {name}"


async def run_in_threadsafe_coro(message: str) -> str:
    """
    A simple coroutine to be run via run_coroutine_threadsafe.
    """
    current_task: Optional[asyncio.Task[Any]] = asyncio.current_task()
    task_name: str = current_task.get_name() if current_task and current_task.get_name() else "UnknownTask"
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Task '{task_name}' (from threadsafe): Received message: '{message}'"
    )
    await asyncio.sleep(0.5)
    return f"Coroutine done: {message}"


def threadsafe_submission_target(loop: asyncio.AbstractEventLoop) -> None:
    """
    Function to be run in a separate thread to submit a coroutine
    to the main event loop using asyncio.run_coroutine_threadsafe.
    """
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Thread '{threading.current_thread().name}': Submitting coroutine to event loop..."
    )
    coro = run_in_threadsafe_coro("Hello from another thread!")
    future: concurrent.futures.Future[str] = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        # Wait for result with an optional timeout argument from the submitting thread's perspective
        result: str = future.result(timeout=2)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Thread '{threading.current_thread().name}': Coroutine result: '{result}'"
        )
    except concurrent.futures.TimeoutError:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Thread '{threading.current_thread().name}': Coroutine submission timed out. Cancelling task."
        )
        future.cancel()  # If timeout, request cancellation of the task in the event loop
    except Exception as e:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Thread '{threading.current_thread().name}': Coroutine raised exception: {e!r}"
        )


async def eager_task_factory_demo() -> None:
    """
    Demonstrates asyncio.eager_task_factory (requires Python 3.12+).
    This function must be run in its own asyncio.run() block because
    `set_task_factory` modifies the event loop's global behavior.
    """
    print("\n--- Demonstrating Eager Task Factory (Requires Python 3.12+) ---")

    # Check for Python version compatibility
    if not hasattr(asyncio, "eager_task_factory"):
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Skipping Eager Task Factory demo: asyncio.eager_task_factory requires Python 3.12+."
        )
        print("--- Eager Task Factory Demo Skipped ---\n")
        return

    async def immediate_coro() -> str:
        """A coroutine that does not await, thus finishes eagerly."""
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Eager Task: Immediate coro running. (This should print immediately after task creation)"
        )
        return "Eagerly Done"

    async def blocking_coro() -> str:
        """A coroutine that awaits, thus starts eagerly but then schedules to event loop."""
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Eager Task: Blocking coro running, will await. (This should print immediately)"
        )
        await asyncio.sleep(0.1)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Eager Task: Blocking coro resumed. (This should print after sleep)"
        )
        return "Not Eagerly Done"

    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

    # Set the eager factory for the current running loop.
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Setting event loop task factory to asyncio.eager_task_factory..."
    )
    loop.set_task_factory(asyncio.eager_task_factory)

    print(f"[{datetime.datetime.now().strftime('%X')}] Creating immediate_task (expects eager completion)...")
    # This task will complete synchronously during its creation because it doesn't await.
    immediate_task: asyncio.Task[str] = loop.create_task(immediate_coro(), name="ImmediateEagerTask")
    print(f"[{datetime.datetime.now().strftime('%X')}] immediate_task created. Is it done? {immediate_task.done()}")
    if immediate_task.done():  # It should be done immediately
        print(f"[{datetime.datetime.now().strftime('%X')}] Result of immediate_task: {immediate_task.result()}")
    else:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] immediate_task not done immediately (unexpected). Awaiting..."
        )
        await immediate_task
        print(f"[{datetime.datetime.now().strftime('%X')}] Result of immediate_task: {immediate_task.result()}")

    print(f"[{datetime.datetime.now().strftime('%X')}] Creating blocking_task (expects eager start, then schedule)...")
    # This task will start eagerly, print its first message, then yield control via await,
    # and then be scheduled onto the event loop.
    blocking_task: asyncio.Task[str] = loop.create_task(blocking_coro(), name="BlockingEagerTask")
    print(
        f"[{datetime.datetime.now().strftime('%X')}] blocking_task created. Is it done? {blocking_task.done()}"
    )  # Should be False initially
    await blocking_task  # Wait for it to complete on the event loop
    print(f"[{datetime.datetime.now().strftime('%X')}] Result of blocking_task: {blocking_task.result()}")

    # Reset task factory to default for good practice.
    # If the loop were to continue being used for other demos, this would be crucial.
    loop.set_task_factory(None)  # Restore default factory by setting to None
    print("--- Eager Task Factory Demo Complete ---\n")


def get_task_status_str(task: asyncio.Task[Any]) -> str:
    """Helper to safely get task status for printing."""
    if not task.done():
        return f"done={task.done()}, pending"

    status_parts: List[str] = [f"done={task.done()}"]
    if task.cancelled():
        status_parts.append(f"cancelled={task.cancelled()}")
    elif task.exception():
        status_parts.append(f"exception={task.exception()!r}")
    else:
        # If task is done, not cancelled, and no exception, it must have completed successfully.
        try:
            status_parts.append(f"result={task.result()!r}")
        except asyncio.InvalidStateError:  # Should not happen if task is done and not cancelled/exception.
            status_parts.append("result=InvalidStateError (task done but result not ready?)")
        except Exception as e:  # Catch any unexpected exceptions from result() itself
            status_parts.append(f"result_access_error={e!r}")
    return ", ".join(status_parts)


async def main() -> None:
    """
    Main function demonstrating various asyncio APIs.
    """
    print("--- Starting Asyncio Demo ---")
    start_time_main: float = time.time()

    # --- 1. Basic Coroutine and Task Creation ---
    print("\n--- Basic Coroutine and Task Creation ---")
    await simulate_io_task("simple_sequential_task", 0.5)  # Await directly for sequential execution
    task_a: asyncio.Task[str] = asyncio.create_task(simulate_io_task("task_A", 1.0), name="MyTaskA")
    # Task.set_name() can be used to explicitly set a name, overriding auto-generated names.
    # If name is passed to create_task, it's already set. Here, we demonstrate re-setting or late setting.
    task_b_coro: Any = simulate_io_task("task_B", 0.7)
    task_b: asyncio.Task[str] = asyncio.create_task(task_b_coro)  # No name given at creation
    task_b.set_name("MyTaskB")  # Set name using Task.set_name()
    print(f"[{datetime.datetime.now().strftime('%X')}] Tasks created: '{task_a.get_name()}', '{task_b.get_name()}'")

    # --- 2. Introspection and Task Object Methods ---
    print("\n--- Task Introspection ---")
    current_t: Optional[asyncio.Task[Any]] = asyncio.current_task()
    print(f"[{datetime.datetime.now().strftime('%X')}] Current task: '{current_t.get_name() if current_t else 'None'}'")

    # Filter out internal asyncio tasks (e.g., 'asyncio#_wait_for_task') for clearer output
    all_active_tasks: List[asyncio.Task[Any]] = [
        t
        for t in asyncio.all_tasks()
        if t is not current_t and not (t.get_name() and t.get_name().startswith("asyncio-"))
    ]
    print(
        f"[{datetime.datetime.now().strftime('%X')}] All active user-defined tasks: {[t.get_name() for t in all_active_tasks if t.get_name()]}"
    )

    # Demonstrate get_coro() and get_context()
    if task_a.get_coro():  # get_coro can be None for eager tasks that completed synchronously (not applicable here directly, but good practice)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Task '{task_a.get_name()}' holds coroutine: {asyncio.iscoroutine(task_a.get_coro())}"
        )
    print(f"[{datetime.datetime.now().strftime('%X')}] Task '{task_a.get_name()}' context: {task_a.get_context()}")

    # Await to get results
    results_a_b: List[str] = await asyncio.gather(task_a, task_b)
    print(f"[{datetime.datetime.now().strftime('%X')}] Results of A & B: {results_a_b}")

    # --- 3. Running Tasks Concurrently with asyncio.gather ---
    print("\n--- Concurrency with asyncio.gather ---")

    # Scenario 1: return_exceptions=True - gather will collect results and exceptions
    task_c_coro: Any = simulate_io_task("task_C", 1.2)
    task_d_coro: Any = simulate_io_task("task_D", 0.8, will_fail=True)  # This one will fail
    task_e_coro: Any = simulate_io_task("task_E", 0.5)

    print(f"[{datetime.datetime.now().strftime('%X')}] Gathering tasks C, D(failing), E with return_exceptions=True...")
    gathered_results_with_exceptions: List[Union[str, Exception]] = await asyncio.gather(
        task_c_coro, task_d_coro, task_e_coro, return_exceptions=True
    )
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Gathered results (with exceptions): {gathered_results_with_exceptions}"
    )
    for res in gathered_results_with_exceptions:
        if isinstance(res, Exception):
            print(f"  - Caught exception in gather result: {res!r}")
        else:
            print(f"  - Successful result: {res}")

    # Scenario 2: return_exceptions=False (default) - gather will propagate the first exception immediately
    # Note: If `gather` is passed coroutines, it implicitly creates tasks. To inspect task states afterwards,
    # it's better to explicitly create tasks and pass them.
    task_f: asyncio.Task[str] = asyncio.create_task(simulate_io_task("task_F", 1.2), name="TaskF")
    task_g: asyncio.Task[str] = asyncio.create_task(
        simulate_io_task("task_G", 0.8, will_fail=True), name="TaskG"
    )  # This one will fail
    task_h: asyncio.Task[str] = asyncio.create_task(simulate_io_task("task_H", 0.5), name="TaskH")

    print(
        f"[{datetime.datetime.now().strftime('%X')}] Gathering explicit tasks (F, G(failing), H) with return_exceptions=False..."
    )
    try:
        await asyncio.gather(task_f, task_g, task_h)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Gathered explicit tasks completed successfully (UNEXPECTED, G should fail)."
        )
    except ValueError as e:  # Specific exception from simulate_io_task
        print(f"[{datetime.datetime.now().strftime('%X')}] Caught specific exception from gather explicit tasks: {e!r}")
    except ExceptionGroup as eg:  # In some complex nested scenarios, might yield ExceptionGroup (Python 3.11+)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Caught ExceptionGroup from gather explicit tasks: {eg.exceptions}"
        )
    except Exception as e:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Caught unexpected generic exception from gather explicit tasks: {e!r}"
        )

    # After `gather` raises an exception (with return_exceptions=False),
    # the other tasks passed to `gather` are *not* automatically cancelled by `gather` itself.
    # They might complete or remain pending if no one awaits them.
    # To ensure cleanup and safe inspection, explicitly cancel and await all tasks.
    for task in [task_f, task_g, task_h]:
        if not task.done():  # Check if the task is still running/pending
            task.cancel()  # Request cancellation

    # Now, await all tasks, including those that might have been cancelled or already completed.
    # Use return_exceptions=True to ensure gather doesn't raise a new exception if one of these tasks failed/cancelled.
    await asyncio.gather(task_f, task_g, task_h, return_exceptions=True)

    # Now that all tasks are guaranteed to be done, their state can be safely accessed.
    print(
        f"[{datetime.datetime.now().strftime('%X')}] State of '{task_f.get_name()}' (after gather & cleanup): {get_task_status_str(task_f)}"
    )
    print(
        f"[{datetime.datetime.now().strftime('%X')}] State of '{task_g.get_name()}' (after gather & cleanup): {get_task_status_str(task_g)}"
    )
    print(
        f"[{datetime.datetime.now().strftime('%X')}] State of '{task_h.get_name()}' (after gather & cleanup): {get_task_status_str(task_h)}"
    )

    # --- 4. Task Groups (Structured Concurrency - Requires Python 3.11+) ---
    print("\n--- Task Groups (Structured Concurrency - Requires Python 3.11+) ---")
    if not hasattr(asyncio, "TaskGroup"):
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Skipping TaskGroup demo: asyncio.TaskGroup requires Python 3.11+."
        )
    else:

        async def task_group_worker(name: str, duration: float) -> str:
            current_task_tg: Optional[asyncio.Task[Any]] = asyncio.current_task()
            task_display_name_tg: str = (
                current_task_tg.get_name() if current_task_tg and current_task_tg.get_name() else name
            )
            print(f"[{datetime.datetime.now().strftime('%X')}] TaskGroup Worker '{task_display_name_tg}': Starting...")
            await asyncio.sleep(duration)
            print(f"[{datetime.datetime.now().strftime('%X')}] TaskGroup Worker '{task_display_name_tg}': Done.")
            return f"Worker {name} Result"

        async def task_group_fail_worker(name: str, duration: float) -> str:
            current_task_tgf: Optional[asyncio.Task[Any]] = asyncio.current_task()
            task_display_name_tgf: str = (
                current_task_tgf.get_name() if current_task_tgf and current_task_tgf.get_name() else name
            )
            print(
                f"[{datetime.datetime.now().strftime('%X')}] TaskGroup Fail Worker '{task_display_name_tgf}': Starting..."
            )
            await asyncio.sleep(duration)
            print(
                f"[{datetime.datetime.now().strftime('%X')}] TaskGroup Fail Worker '{task_display_name_tgf}': Will fail now."
            )
            raise RuntimeError(f"Simulated failure from {name}")

        try:
            async with asyncio.TaskGroup() as tg:
                # TaskGroup automatically assigns default names if not specified, e.g., "TaskGroup-1"
                tg_task1: asyncio.Task[str] = tg.create_task(task_group_worker("TG-1", 1.5), name="TG-Task1")
                tg_task2: asyncio.Task[str] = tg.create_task(
                    task_group_fail_worker("TG-2-Fail", 0.5), name="TG-Task2-Fail"
                )
                tg_task3: asyncio.Task[str] = tg.create_task(task_group_worker("TG-3", 2.0), name="TG-Task3")
                print(f"[{datetime.datetime.now().strftime('%X')}] TaskGroup: Tasks submitted. Waiting...")
            # This part will only be reached if ALL tasks in the TaskGroup complete without unhandled exceptions.
            # Given tg_task2-Fail, this block should ideally not be reached.
            print(
                f"[{datetime.datetime.now().strftime('%X')}] TaskGroup: All tasks completed successfully (UNEXPECTED for this demo)."
            )
            print(f"TG-Task1 Result: {tg_task1.result()}")
            print(f"TG-Task2-Fail State: done={tg_task2.done()}, exception={tg_task2.exception()}")
            print(f"TG-Task3 State: done={tg_task3.done()}, exception={tg_task3.exception()}")
        except* RuntimeError as eg:  # ExceptionGroup, requires Python 3.11+ for `except*`
            print(
                f"[{datetime.datetime.now().strftime('%X')}] TaskGroup: Caught expected ExceptionGroup due to task failure!"
            )
            for exc in eg.exceptions:
                print(f"  - Exception: {exc!r}")
            # Inspect task states after TaskGroup exits
            print(f"TG-Task1 State: {get_task_status_str(tg_task1)}")
            print(f"TG-Task2-Fail State: {get_task_status_str(tg_task2)}")
            print(f"TG-Task3 State: {get_task_status_str(tg_task3)}")
            # TG-Task1 should be done, TG-Task2-Fail should have its RuntimeError, TG-Task3 should be cancelled if it was still running when TG-2-Fail failed.

        # Example of terminating a task group via exception (as per documentation)
        class TerminateTaskGroup(Exception):
            """Custom exception raised to gracefully terminate a task group."""

        async def force_terminate_task_group() -> None:
            """Used to force termination of a task group by raising an exception."""
            print(f"[{datetime.datetime.now().strftime('%X')}] Force terminate: Raising exception.")
            await asyncio.sleep(0.01)  # Give a tiny moment for other tasks to start before terminating
            raise TerminateTaskGroup()

        async def job_for_termination(task_id: int, sleep_time: float) -> None:
            print(f"[{datetime.datetime.now().strftime('%X')}] Task {task_id}: start")
            try:
                await asyncio.sleep(sleep_time)
                print(f"[{datetime.datetime.now().strftime('%X')}] Task {task_id}: done")
            except asyncio.CancelledError:
                print(f"[{datetime.datetime.now().strftime('%X')}] Task {task_id}: cancelled during sleep.")
            except Exception as e:
                print(f"[{datetime.datetime.now().strftime('%X')}] Task {task_id}: failed with {e!r}.")

        print("\n--- Demonstrating TaskGroup termination (via special exception) ---")
        try:
            async with asyncio.TaskGroup() as group:
                job1_task: asyncio.Task[None] = group.create_task(job_for_termination(10, 0.5), name="TerminationJob10")
                job2_task: asyncio.Task[None] = group.create_task(job_for_termination(11, 1.5), name="TerminationJob11")
                await asyncio.sleep(0.7)  # Let some tasks run. Job 10 should be done, Job 11 should be running.
                group.create_task(
                    force_terminate_task_group(), name="TerminatorTask"
                )  # This task will terminate the group
                # All tasks in the group, including job2_task, will be cancelled when TerminateTaskGroup is raised and handled by TaskGroup.
        except* TerminateTaskGroup:  # Catch the specific ExceptionGroup containing TerminateTaskGroup (Python 3.11+)
            print(f"[{datetime.datetime.now().strftime('%X')}] TaskGroup termination via exception caught and handled.")
            print(f"TerminationJob10 status: {get_task_status_str(job1_task)}")  # Should be done
            print(f"TerminationJob11 status: {get_task_status_str(job2_task)}")  # Should be cancelled

    # --- 5. Timeout Mechanisms (asyncio.timeout and asyncio.timeout_at require Python 3.11+) ---
    print("\n--- Timeout Mechanisms ---")

    # asyncio.timeout(delay) context manager
    long_task_for_timeout_coro: Any = simulate_io_task("timeout_target", 2.0)
    try:
        print(f"[{datetime.datetime.now().strftime('%X')}] Attempting task with asyncio.timeout(1.0)...")
        # asyncio.timeout context manager requires Python 3.11+
        if hasattr(asyncio, "timeout"):
            async with asyncio.timeout(1.0) as cm:
                await long_task_for_timeout_coro
                print(
                    f"[{datetime.datetime.now().strftime('%X')}] Task finished within timeout (UNEXPECTED for 2s task)."
                )
            if cm.expired():  # Check if the context manager itself considers it expired
                print(f"[{datetime.datetime.now().strftime('%X')}] Timeout context manager reported expired.")
        else:
            print(f"[{datetime.datetime.now().strftime('%X')}] Skipping asyncio.timeout demo: requires Python 3.11+.")
            await long_task_for_timeout_coro  # Run without timeout for compatibility
    except TimeoutError:
        print(f"[{datetime.datetime.now().strftime('%X')}] Caught TimeoutError from asyncio.timeout!")
        # The task passed to `await` inside `asyncio.timeout` gets cancelled internally.
        # The `TimeoutError` is then re-raised *outside* the `async with` block.
        # The `simulate_io_task`'s `finally` block will print the cancellation status.

    # asyncio.timeout_at(when) context manager
    long_task_for_timeout_at_coro: Any = simulate_io_task("timeout_at_target", 2.0)
    loop = asyncio.get_running_loop()
    deadline: float = loop.time() + 1.0  # 1 second from now (absolute time)
    try:
        if hasattr(asyncio, "timeout_at"):
            print(
                f"[{datetime.datetime.now().strftime('%X')}] Attempting task with asyncio.timeout_at({deadline:.2f})..."
            )
            async with asyncio.timeout_at(deadline) as cm_at:
                # We can reschedule even timeout_at
                # cm_at.reschedule(loop.time() + 0.5) # Example of rescheduling it to an even earlier time
                await long_task_for_timeout_at_coro
                print(f"[{datetime.datetime.now().strftime('%X')}] Task finished within timeout_at (UNEXPECTED).")
        else:
            print(
                f"[{datetime.datetime.now().strftime('%X')}] Skipping asyncio.timeout_at demo: requires Python 3.11+."
            )
            await long_task_for_timeout_at_coro  # Run without timeout for compatibility
    except TimeoutError:
        print(f"[{datetime.datetime.now().strftime('%X')}] Caught TimeoutError from asyncio.timeout_at!")

    # asyncio.wait_for(aw, timeout) function (exists since Python 3.4)
    eternity_task_explicit: asyncio.Task[str] = asyncio.create_task(
        simulate_io_task("eternity_explicit", 3600.0), name="EternityTask"
    )  # Very long task
    try:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Waiting for eternity task with asyncio.wait_for({eternity_task_explicit.get_name()}, timeout=1.0)..."
        )
        await asyncio.wait_for(
            eternity_task_explicit, timeout=1.0
        )  # wait_for wraps coro in a task if not already a task/future
        print(f"[{datetime.datetime.now().strftime('%X')}] Eternity task finished (UNEXPECTED).")
    except TimeoutError:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Caught TimeoutError from asyncio.wait_for! Eternity task was cancelled."
        )
        # `wait_for` ensures the inner task is cancelled and propagates `TimeoutError`.
        # The underlying task is now done due to cancellation.
        await asyncio.sleep(0.01)  # Give it a moment for cancellation to fully process
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Is '{eternity_task_explicit.get_name()}' done? {eternity_task_explicit.done()}"
        )
        print(
            f"[{datetime.datetime.now().strftime('%X')}] '{eternity_task_explicit.get_name()}' cancelled status: {eternity_task_explicit.cancelled()}"
        )

    # --- 6. Task Cancellation and Shielding ---
    print("\n--- Task Cancellation and Shielding ---")
    cancel_me_task: asyncio.Task[str] = asyncio.create_task(simulate_io_task("cancel_me", 5.0), name="CancelMeTask")
    await asyncio.sleep(0.5)  # Let it start
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Main: Requesting cancellation of '{cancel_me_task.get_name()}'..."
    )
    # cancel() adds a cancellation request.
    cancel_me_task.cancel("Manual cancellation request for CancelMeTask")
    # Task.cancelling() requires Python 3.11+
    if hasattr(cancel_me_task, "cancelling"):
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Main: '{cancel_me_task.get_name()}' cancelling count: {cancel_me_task.cancelling()}"
        )
    else:
        print(f"[{datetime.datetime.now().strftime('%X')}] Main: Task.cancelling() requires Python 3.11+.")

    try:
        await cancel_me_task  # Await to observe the cancellation
    except asyncio.CancelledError as e:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Main: Caught CancelledError for '{cancel_me_task.get_name()}'! Message: {e}"
        )
    # After `await task` for a cancelled task, its `done()` is True and `cancelled()` is True.
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Task '{cancel_me_task.get_name()}' done status: {cancel_me_task.done()}, cancelled status: {cancel_me_task.cancelled()}"
    )

    # Demonstrate uncancel() and suppressing cancellation (generally discouraged in real code, requires Python 3.11+)
    if hasattr(asyncio.Task, "uncancel"):

        async def suppress_cancel_coro(name: str) -> str:
            current_task_sc: Optional[asyncio.Task[Any]] = asyncio.current_task()
            task_display_name_sc: str = (
                current_task_sc.get_name() if current_task_sc and current_task_sc.get_name() else name
            )
            print(
                f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_sc}': Starting, will try to suppress cancel."
            )
            try:
                await asyncio.sleep(2)
                print(
                    f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_sc}': Sleep done (UNEXPECTED if cancelled and not suppressed)."
                )
            except asyncio.CancelledError:
                print(
                    f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_sc}': Caught CancelledError, attempting to suppress it!"
                )
                if current_task_sc:
                    # uncancel() decrements the cancellation request count.
                    # If it reaches zero, the cancellation state is removed.
                    remaining_cancels: int = current_task_sc.uncancel()
                    print(
                        f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_sc}': Uncancelled, remaining requests: {remaining_cancels}"
                    )
                    if remaining_cancels == 0:
                        print(
                            f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_sc}': Cancellation state effectively removed."
                        )
                await asyncio.sleep(1)  # Continue after suppressing
                print(
                    f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_sc}': Finished after suppressing cancellation."
                )
            return f"Result from {name} (suppressed cancel)"

        suppress_task: asyncio.Task[str] = asyncio.create_task(suppress_cancel_coro("suppress_me"), name="SuppressTask")
        await asyncio.sleep(0.1)
        print(f"[{datetime.datetime.now().strftime('%X')}] Main: Requesting cancellation of 'SuppressTask'...")
        suppress_task.cancel()
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Main: '{suppress_task.get_name()}' cancelling count: {suppress_task.cancelling()}"
        )
        await suppress_task  # Wait for it to complete
        # Since `uncancel()` was called and reduced the count to zero, `cancelled()` should return False.
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Main: '{suppress_task.get_name()}' done. Cancelled status: {suppress_task.cancelled()} (should be False because it uncancelled)"
        )
    else:
        print(f"[{datetime.datetime.now().strftime('%X')}] Skipping Task.uncancel() demo: requires Python 3.11+.")

    # asyncio.shield(aw) - Protect an awaitable from being cancelled by its awaiter.
    shielded_task_actual: asyncio.Task[str] = asyncio.create_task(
        simulate_io_task("shielded_target", 2.0), name="ShieldedTaskActual"
    )
    try:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Trying to cancel a shielded task's awaiter (timeout 0.5s)..."
        )
        # `asyncio.wait_for` will try to cancel its argument (`asyncio.shield(...)`) if timeout occurs.
        # However, `asyncio.shield` makes its *inner* argument (`shielded_task_actual`) immune to *this specific* cancellation.
        # The `await asyncio.shield(...)` expression itself *will* still raise `TimeoutError`.
        await asyncio.wait_for(asyncio.shield(shielded_task_actual), timeout=0.5)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Shielded task completed (UNEXPECTED, wait_for should have timed out)."
        )
    except TimeoutError:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Caught TimeoutError for shield wrapper. '{shielded_task_actual.get_name()}' should still be running because it was shielded."
        )
        # Verify the actual shielded task's status:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Is '{shielded_task_actual.get_name()}' done? {shielded_task_actual.done()}"
        )
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Is '{shielded_task_actual.get_name()}' cancelled? {shielded_task_actual.cancelled()}"
        )
        await asyncio.sleep(
            1.8
        )  # Give the shielded task time to complete (its full duration was 2.0s; 0.5s passed before timeout)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] After waiting for shielded task. Done status: {shielded_task_actual.done()}. Awaiting its completion."
        )
        result_shielded: str = await shielded_task_actual  # Await it to get its result and ensure it's truly done.
        print(f"[{datetime.datetime.now().strftime('%X')}] Shielded task result: {result_shielded}")

    # --- 7. Waiting Primitives (asyncio.wait and asyncio.as_completed) ---
    print("\n--- Waiting Primitives ---")

    # asyncio.wait(aws, *, timeout=None, return_when=ALL_COMPLETED)
    # Note: Passed awaitables must be Future-like objects (e.g., Tasks), not bare coroutines (since Python 3.11 for `wait()`)
    wait_tasks_1: List[asyncio.Task[str]] = [
        asyncio.create_task(simulate_io_task("wait_task_1", 1.0), name="WaitTask1"),
        asyncio.create_task(simulate_io_task("wait_task_2", 2.5), name="WaitTask2"),
        asyncio.create_task(simulate_io_task("wait_task_3", 0.7, will_fail=True), name="WaitTask3-Fail"),
        asyncio.create_task(simulate_io_task("wait_task_4", 1.5), name="WaitTask4"),
    ]

    print(f"[{datetime.datetime.now().strftime('%X')}] asyncio.wait (FIRST_COMPLETED, timeout=1.0)...")
    # Returns when ANY task completes or timeout occurs. It does NOT cancel other tasks.
    done: Set[asyncio.Future[Any]]
    pending: Set[asyncio.Future[Any]]
    done, pending = await asyncio.wait(wait_tasks_1, timeout=1.0, return_when=asyncio.FIRST_COMPLETED)
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Done (FIRST_COMPLETED): {[t.get_name() for t in done if isinstance(t, asyncio.Task) and t.get_name()]} | Pending: {[t.get_name() for t in pending if isinstance(t, asyncio.Task) and t.get_name()]}"
    )
    for t in done:
        if isinstance(t, asyncio.Task):
            print(f"  - Completed task '{t.get_name()}' status: {get_task_status_str(t)}")
    for t_pending in pending:  # For demo clarity, cancel pending tasks to clean up the loop
        if (
            isinstance(t_pending, asyncio.Task) and not t_pending.done()
        ):  # Only cancel if not already done by some other means
            t_pending.cancel()
    if pending:  # Await pending tasks to ensure they handle cancellation and are truly done.
        # Use gather with return_exceptions=True to await multiple potentially cancelled/failed tasks
        await asyncio.gather(*pending, return_exceptions=True)
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Pending tasks (after explicit cancellation): {[t.get_name() for t in pending if isinstance(t, asyncio.Task) and t.get_name() and not t.done()]}"
        )

    # Recreate tasks for next wait example (FIRST_EXCEPTION)
    wait_tasks_2: List[asyncio.Task[str]] = [
        asyncio.create_task(simulate_io_task("wait_task_5", 1.0), name="WaitTask5"),
        asyncio.create_task(simulate_io_task("wait_task_6", 2.5), name="WaitTask6"),
        asyncio.create_task(
            simulate_io_task("wait_task_7", 0.7, will_fail=True), name="WaitTask7-Fail"
        ),  # This one fails first
        asyncio.create_task(simulate_io_task("wait_task_8", 1.5), name="WaitTask8"),
    ]
    print(f"[{datetime.datetime.now().strftime('%X')}] asyncio.wait (FIRST_EXCEPTION)...")
    # Returns when ANY task raises an exception. If no task raises an exception then it is equivalent to ALL_COMPLETED.
    done, pending = await asyncio.wait(wait_tasks_2, return_when=asyncio.FIRST_EXCEPTION)
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Done (FIRST_EXCEPTION): {[t.get_name() for t in done if isinstance(t, asyncio.Task) and t.get_name()]} | Pending: {[t.get_name() for t in pending if isinstance(t, asyncio.Task) and t.get_name()]}"
    )
    for t in done:
        if isinstance(t, asyncio.Task):
            print(f"  - Completed task '{t.get_name()}' status: {get_task_status_str(t)}")
    for t_pending in pending:  # Clean up pending
        if isinstance(t_pending, asyncio.Task) and not t_pending.done():
            t_pending.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    # Recreate tasks for ALL_COMPLETED
    wait_tasks_3: List[asyncio.Task[str]] = [
        asyncio.create_task(simulate_io_task("wait_task_9", 1.0), name="WaitTask9"),
        asyncio.create_task(simulate_io_task("wait_task_10", 0.5), name="WaitTask10"),
    ]
    print(f"[{datetime.datetime.now().strftime('%X')}] asyncio.wait (ALL_COMPLETED)...")
    # Returns when ALL tasks finish or are cancelled.
    done, pending = await asyncio.wait(wait_tasks_3, return_when=asyncio.ALL_COMPLETED)
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Done (ALL_COMPLETED): {[t.get_name() for t in done if isinstance(t, asyncio.Task) and t.get_name()]} | Pending: {[t.get_name() for t in pending if isinstance(t, asyncio.Task) and t.get_name()]}"
    )
    for t in done:
        if isinstance(t, asyncio.Task):
            print(f"[{datetime.datetime.now().strftime('%X')}] '{t.get_name()}' status: {get_task_status_str(t)}")

    # asyncio.as_completed(aws, *, timeout=None) - Iterate results as they finish.
    as_completed_tasks: List[asyncio.Task[str]] = [
        asyncio.create_task(simulate_io_task("as_comp_1", 1.0), name="AsCompTask1"),
        asyncio.create_task(simulate_io_task("as_comp_2", 0.5), name="AsCompTask2"),
        asyncio.create_task(simulate_io_task("as_comp_3", 1.5), name="AsCompTask3"),
    ]
    print(f"[{datetime.datetime.now().strftime('%X')}] asyncio.as_completed (iterating as they finish)...")
    # In Python 3.13+, `as_completed` yields the original Task objects if they were tasks/futures.
    # Before 3.13, it yielded new wrapper awaitable objects.
    for i, completed_awaitable in enumerate(asyncio.as_completed(as_completed_tasks)):
        try:
            result: Any = await completed_awaitable  # Await each one as it finishes
            original_task_name: str = "N/A"
            # It's better to check if it's an asyncio.Task (which will be true in 3.13+)
            # and then get its name and status.
            if isinstance(completed_awaitable, asyncio.Task):
                original_task_name = completed_awaitable.get_name() if completed_awaitable.get_name() else "UnnamedTask"
                print(
                    f"[{datetime.datetime.now().strftime('%X')}] Completed awaitable {i + 1}: {result!r} (Original task name: {original_task_name})"
                )
                print(f"  - Original task state: {get_task_status_str(completed_awaitable)}")
            else:  # For older Python versions where as_completed yields wrapper awaitables
                print(f"[{datetime.datetime.now().strftime('%X')}] Completed awaitable {i + 1}: {result!r}")
        except Exception as e:
            original_task_name = "N/A"
            if isinstance(completed_awaitable, asyncio.Task):
                original_task_name = completed_awaitable.get_name() if completed_awaitable.get_name() else "UnnamedTask"
                print(
                    f"[{datetime.datetime.now().strftime('%X')}] Completed awaitable {i + 1} failed: {e!r} (Original task name: {original_task_name})"
                )
                print(f"  - Original task state: {get_task_status_str(completed_awaitable)}")
            else:
                print(f"[{datetime.datetime.now().strftime('%X')}] Completed awaitable {i + 1} failed: {e!r}")

    # --- 8. Running in Threads (asyncio.to_thread - Requires Python 3.9+) ---
    print("\n--- Running Blocking Code in Threads with asyncio.to_thread ---")
    if not hasattr(asyncio, "to_thread"):
        print(f"[{datetime.datetime.now().strftime('%X')}] Skipping asyncio.to_thread demo: requires Python 3.9+.")
    else:
        # This runs `simulate_blocking_call` in a separate thread without blocking the event loop.
        # `simulate_io_task` runs concurrently on the event loop.
        await asyncio.gather(
            asyncio.to_thread(simulate_blocking_call, "blocking_func_1", 1.0),
            simulate_io_task("ConcurrentAsyncTask", 0.5),
        )
        print(f"[{datetime.datetime.now().strftime('%X')}] asyncio.to_thread demo finished.")

    # --- 9. Scheduling From Other Threads (asyncio.run_coroutine_threadsafe) ---
    print("\n--- Scheduling from Other Threads with asyncio.run_coroutine_threadsafe ---")
    current_loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    # Using ThreadPoolExecutor as `run_in_executor` provides a convenient way to run
    # a blocking function (which `threadsafe_submission_target` is for this context)
    # in a separate thread.
    thread_executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Run `threadsafe_submission_target` in a separate thread.
    # This function itself is blocking (due to `future.result`), but it's executed in a separate thread.
    # The important part is that `run_coroutine_threadsafe` inside it schedules to the main event loop.
    print(f"[{datetime.datetime.now().strftime('%X')}] Main: Submitting thread to executor...")
    loop_future: concurrent.futures.Future[None] = current_loop.run_in_executor(
        thread_executor, threadsafe_submission_target, current_loop
    )
    await loop_future  # Wait for the thread to complete its submission and wait for result
    thread_executor.shutdown(wait=True)  # Clean up the thread pool
    print(f"[{datetime.datetime.now().strftime('%X')}] Threadsafe submission demo finished.")

    # --- 10. Background Tasks Management (fire-and-forget) ---
    print("\n--- Background Tasks Management (fire-and-forget) ---")

    async def background_worker(task_id: int, duration: float) -> str:
        current_task_bw: Optional[asyncio.Task[Any]] = asyncio.current_task()
        task_display_name_bw: str = (
            current_task_bw.get_name() if current_task_bw and current_task_bw.get_name() else f"Background-{task_id}"
        )
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Background Task '{task_display_name_bw}': Starting for {duration:.2f}s..."
        )
        await asyncio.sleep(duration)
        print(f"[{datetime.datetime.now().strftime('%X')}] Background Task '{task_display_name_bw}': Completed.")
        return f"Background {task_id} Done"

    print(f"[{datetime.datetime.now().strftime('%X')}] Creating background tasks (will discard themselves from set)...")
    for i in range(3):
        task_name: str = f"BackgroundTask-{i + 1}"
        task: asyncio.Task[str] = asyncio.create_task(
            background_worker(i + 1, random.uniform(0.5, 1.5)), name=task_name
        )
        background_tasks.add(task)
        # Use add_done_callback to remove the task from our set when it's done.
        # This prevents the set from growing indefinitely and avoids holding strong references to finished tasks.
        task.add_done_callback(background_tasks.discard)

    # Let background tasks run for a bit
    await asyncio.sleep(1.0)
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Main: Allowing background tasks to run. Current background tasks in set: {[t.get_name() for t in background_tasks if t.get_name()]}"
    )
    await asyncio.sleep(2.0)  # Wait longer to ensure they all finish
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Main: After waiting for background tasks. Remaining background tasks in set: {[t.get_name() for t in background_tasks if t.get_name()]}"
    )

    # --- 11. Task Stack Inspection ---
    print("\n--- Task Stack Inspection ---")

    async def nested_coro_1(name_nc1: str) -> None:
        current_task_nc1: Optional[asyncio.Task[Any]] = asyncio.current_task()
        task_display_name_nc1: str = (
            current_task_nc1.get_name() if current_task_nc1 and current_task_nc1.get_name() else name_nc1
        )
        await asyncio.sleep(0.1)  # Simulate some work
        print(f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_nc1}': Nested Coro 1 '{name_nc1}' done.")

    async def nested_coro_2(name_nc2: str) -> None:
        current_task_nc2: Optional[asyncio.Task[Any]] = asyncio.current_task()
        task_display_name_nc2: str = (
            current_task_nc2.get_name() if current_task_nc2 and current_task_nc2.get_name() else name_nc2
        )
        await nested_coro_1(f"{name_nc2}_sub")
        await asyncio.sleep(0.2)  # Simulate some more work
        print(f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_nc2}': Nested Coro 2 '{name_nc2}' done.")

    async def inspect_me_coro(name_im: str) -> None:
        current_task_im: Optional[asyncio.Task[Any]] = asyncio.current_task()
        task_display_name_im: str = (
            current_task_im.get_name() if current_task_im and current_task_im.get_name() else name_im
        )
        print(
            f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_im}': Starting Inspect Me '{name_im}'..."
        )
        await nested_coro_2(f"{name_im}_nested")
        await asyncio.sleep(0.3)
        print(f"[{datetime.datetime.now().strftime('%X')}] '{task_display_name_im}': Inspect Me '{name_im}' done.")
        # Raise an exception to demonstrate traceback frames in get_stack()
        raise ValueError("Simulated error for traceback demo from InspectMeTask")

    inspect_task: asyncio.Task[Any] = asyncio.create_task(inspect_me_coro("InspectTask"), name="InspectMeTask")
    await asyncio.sleep(0.05)  # Let it start and go into nested_coro_2

    print(
        f"[{datetime.datetime.now().strftime('%X')}] Main: Getting stack of '{inspect_task.get_name()}' (before completion/exception)..."
    )
    # For a suspended coroutine, get_stack() returns the stack frame where it is currently suspended.
    stack_frames_before: List[Any] = inspect_task.get_stack()
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Stack frames before: {len(stack_frames_before)} (Expected ~1 for suspended coroutine, can vary based on Python/asyncio internals)"
    )
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Printing stack of '{inspect_task.get_name()}' (will show where it's currently awaiting):"
    )
    inspect_task.print_stack()

    # It's important to await the task to let its exception propagate and be handled,
    # or to allow it to complete.
    try:
        await inspect_task  # Wait for it to complete and raise exception
    except ValueError as e:
        print(
            f"[{datetime.datetime.now().strftime('%X')}] Main: Caught expected exception from '{inspect_task.get_name()}': {e!r}"
        )

    print(
        f"[{datetime.datetime.now().strftime('%X')}] '{inspect_task.get_name()}' done. Exception: {inspect_task.exception()!r}"
    )

    print(
        f"[{datetime.datetime.now().strftime('%X')}] Getting stack of '{inspect_task.get_name()}' (after exception)..."
    )
    # When a coroutine is terminated by an exception, get_stack() returns the traceback frames.
    stack_frames_after: List[Any] = inspect_task.get_stack()
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Stack frames after: {len(stack_frames_after)} (Expected >1 for traceback)"
    )
    print(
        f"[{datetime.datetime.now().strftime('%X')}] Printing traceback of '{inspect_task.get_name()}' (will show the path to the error):"
    )
    inspect_task.print_stack()

    end_time_main: float = time.time()
    print(f"\n--- Asyncio Demo Complete in {end_time_main - start_time_main:.2f} seconds ---")


if __name__ == "__main__":
    # Note on Python Versions:
    # - asyncio.TaskGroup, `except*` for ExceptionGroup, asyncio.timeout, asyncio.timeout_at,
    #   Task.uncancel(), Task.cancelling() require Python 3.11+.
    # - asyncio.eager_task_factory, asyncio.Task(eager_start=...) require Python 3.12+.
    # - asyncio.to_thread requires Python 3.9+.
    # - The provided documentation is for Python 3.13.5.

    try:
        asyncio.run(main())
    except (
        ExceptionGroup
    ) as eg:  # Catching any unhandled ExceptionGroups from main (e.g., from TaskGroup), Python 3.11+
        print(f"\nAn unhandled ExceptionGroup occurred during main execution: {eg}")
        for exc in eg.exceptions:
            print(f"  - Unhandled exception: {exc!r}")
    except Exception as e:  # This is a top-level catch for any single, non-ExceptionGroup exceptions escaping main.
        print(f"\nAn unexpected single error occurred during main execution: {e!r}")

    # Run eager task factory demo in a separate asyncio.run() call.
    # This is important because `loop.set_task_factory()` modifies the
    # event loop's behavior globally for that loop. Running it separately
    # ensures it doesn't interfere with the `main()` demo's behavior or state,
    # and demonstrates a best practice for managing event loop configurations.
    try:
        asyncio.run(eager_task_factory_demo())
    except Exception as e:
        # The TypeError: Task() takes exactly 1 positional argument (2 given)
        # indicates a possible mismatch in Python version or asyncio library
        # implementation where `asyncio.eager_task_factory` might be trying
        # to pass the event loop object positionally to `asyncio.Task.__init__`,
        # which is incorrect in Python 3.10+ (where `loop` is removed from Task constructor)
        # and `eager_task_factory` itself was introduced in 3.12.
        # Ensure your Python version is 3.12 or newer for this demo to run without the TypeError.
        print(f"\nAn unexpected error occurred during eager task factory demo: {e!r}")

    print("\n--- All Demos Finished ---")

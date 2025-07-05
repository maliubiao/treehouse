import datetime
import os
import re
from pathlib import Path
from textwrap import dedent
from typing import Dict, Optional

from colorama import Fore, Style

from .prompts import build_duplicate_check_prompt, build_prompt_for_generation


def _check_and_log_oversized_prompt(
    prompt: str,
    max_context_size: Optional[int],
    model_name: str,
    target_func_for_log: str,
    trace_dir_base: str,
    log_prefix: str,
):
    """
    Checks if the prompt size exceeds the model's context limit and logs it if so.
    """
    if not max_context_size:
        return  # Cannot check if limit is not defined

    try:
        # Approximate token count (1 token ~= 3 chars on average for English/Code)
        estimated_tokens = len(prompt) / 3
        if estimated_tokens > max_context_size:
            # Create a directory for oversized prompts
            trace_dir = Path(trace_dir_base or "llm_traces")
            oversized_dir = trace_dir / "oversized_prompts"
            oversized_dir.mkdir(parents=True, exist_ok=True)

            # Sanitize names for file path
            safe_model_name = re.sub(r'[\\/*?:"<>|]', "_", model_name)
            safe_target_func = re.sub(r'[\\/*?:"<>|]', "_", target_func_for_log)

            # Save the prompt
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            prompt_file_path = oversized_dir / f"{timestamp}_{safe_target_func}_{safe_model_name}.prompt.txt"

            with prompt_file_path.open("w", encoding="utf-8") as f:
                f.write(prompt)

            # Print warning to console
            warning_msg = (
                f"{log_prefix} {Fore.RED}{Style.BRIGHT}WARNING:{Style.RESET_ALL} "
                f"Estimated prompt size (~{int(estimated_tokens)} tokens) "
                f"exceeds model limit ({max_context_size} tokens) for '{target_func_for_log}'."
            )
            print(warning_msg)
            print(Fore.YELLOW + f"{log_prefix} The oversized prompt has been saved to: {prompt_file_path}")
            print(Fore.YELLOW + f"{log_prefix} Continuing with LLM call, but it may be truncated or fail.")
    except Exception as e:
        # This check should not crash the main process
        print(Fore.RED + f"{log_prefix} Error during prompt size check: {e}")


def generation_worker(task: Dict) -> Optional[str]:
    """
    Static worker for parallel test generation. It's self-contained and handles
    the logic for full vs. incremental generation.
    """
    # Unpack task dictionary
    target_func = task["target_func"]
    call_record = task["call_record"]
    case_num = task["case_number"]
    call_idx = task["call_index"]
    total_calls = task["total_calls"]
    existing_code = task.get("existing_code")
    is_incremental = task.get("is_incremental", False)
    from .generator import UnitTestGenerator

    # Re-create a minimal generator instance inside the worker process
    # This ensures process safety for all resources.
    worker_generator = UnitTestGenerator(
        model_name=task["generator_model_name"],
        checker_model_name=task["checker_model_name"],
        trace_llm=task["trace_llm"],
        llm_trace_dir=str(task["trace_dir"]) if task["trace_dir"] else "llm_traces",
        test_mode=task.get("test_mode", False),
    )

    log_prefix = f"[Worker-{os.getpid()}]"
    log_msg = f"{log_prefix} Processing Test Case {case_num}/{total_calls} for '{target_func}'"
    trace_dir_base = str(task["trace_dir"]) if task["trace_dir"] else "llm_traces"

    if is_incremental:
        print(Fore.MAGENTA + f"{log_msg} [INCREMENTAL MODE]" + Style.RESET_ALL)

        # 1. Check for duplicates before generating
        duplicate_prompt = build_duplicate_check_prompt(existing_code, call_record)

        # Check prompt size before sending to LLM
        _check_and_log_oversized_prompt(
            prompt=duplicate_prompt,
            max_context_size=task.get("checker_max_context_size"),
            model_name=task["checker_model_name"],
            target_func_for_log=f"{target_func}-duplicate_check",
            trace_dir_base=trace_dir_base,
            log_prefix=log_prefix,
        )

        print(Fore.CYAN + f"{log_prefix} Checking for duplicate test case...")
        response = worker_generator.model_switch.query(task["checker_model_name"], duplicate_prompt)

        # Normalize response to be safe
        if "YES" in response.upper():
            print(Fore.YELLOW + f"{log_prefix} Skipping duplicate test case for '{target_func}'.")
            return None
        print(Fore.GREEN + f"{log_prefix} No duplicate found. Proceeding with generation.")

    else:
        print(Fore.CYAN + log_msg + Style.RESET_ALL)

    # 2. Build the appropriate prompt (full or incremental)
    prompt_args = {
        "target_func": target_func,
        "call_record": call_record,
        "is_incremental": is_incremental,
    }
    # Add all relevant context from the task dictionary
    for key in [
        "test_class_name",
        "module_to_test",
        "project_root_path",
        "output_file_abs_path",
        "file_path",
        "file_content",
        "symbol_context",
        "existing_code",
        "import_context",
    ]:
        if key in task:
            prompt_args[key] = task[key]

    prompt = build_prompt_for_generation(**prompt_args)

    # Check prompt size before sending to LLM
    _check_and_log_oversized_prompt(
        prompt=prompt,
        max_context_size=task.get("generator_max_context_size"),
        model_name=task["generator_model_name"],
        target_func_for_log=f"{target_func}-generation",
        trace_dir_base=trace_dir_base,
        log_prefix=log_prefix,
    )

    # 3. Query the LLM and extract code
    response_text = worker_generator.model_switch.query(task["generator_model_name"], prompt, stream=False)
    extracted_code = _extract_code_from_response(response_text)

    if not extracted_code:
        print(Fore.RED + f"{log_prefix} Failed to extract code from LLM response for '{target_func}'.")
        return None

    return extracted_code


def _extract_code_from_response(response: str) -> Optional[str]:
    """
    Extracts content from a `[start]...[end]` block. Falls back to markdown.
    """
    # This uses a simplified regex for state machine `_consume_block` logic
    # that existed in the original file, focusing on the most common format.
    start_tag = "[start]"
    end_tag = "[end]"
    start_index = response.find(start_tag)
    if start_index != -1:
        end_index = response.find(end_tag, start_index)
        if end_index != -1:
            code = response[start_index + len(start_tag) : end_index]
            # Use textwrap.dedent to clean up indentation from prompts
            return dedent(code).strip()

    # Fallback for old markdown format
    print(Fore.YELLOW + "Warning: Could not find a '[start]...[end]' block. Trying markdown block.")
    match = re.search(r"```(?:python)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        code = match.group(1)
        return dedent(code).strip()

    # If no tags or markdown, and response is non-empty, maybe the model returned just code
    if response and "def test_" in response:
        print(Fore.YELLOW + "Warning: No block syntax found. Returning raw response as code.")
        return response.strip()

    return None

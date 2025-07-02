import os
import re
from textwrap import dedent
from typing import Dict, Optional

from colorama import Fore, Style

from .prompts import build_duplicate_check_prompt, build_prompt_for_generation


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
    is_incremental = existing_code is not None
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
    log_msg = f"{log_prefix} Generating Test Case {case_num} for '{target_func}' (call {call_idx}/{total_calls})"

    if is_incremental:
        print(Fore.MAGENTA + f"{log_msg} [INCREMENTAL MODE]" + Style.RESET_ALL)

        # 1. Check for duplicates before generating
        duplicate_prompt = build_duplicate_check_prompt(existing_code, call_record)
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
    prompt = build_prompt_for_generation(
        target_func=target_func,
        call_record=call_record,
        is_incremental=is_incremental,
        **{
            k: v
            for k, v in task.items()
            if k
            in [
                "test_class_name",
                "module_to_test",
                "project_root_path",
                "output_file_abs_path",
                "file_path",
                "file_content",
                "symbol_context",
                "existing_code",
            ]
        },
    )

    # 3. Query the LLM and extract code
    response_text = worker_generator.model_switch.query(task["generator_model_name"], prompt, stream=False)
    return _extract_code_from_response(response_text)


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
            return dedent(code).strip()

    # Fallback for old markdown format
    print(Fore.YELLOW + "Warning: Could not find a '[start]...[end]' block. Trying markdown block.")
    match = re.search(r"```(?:python)?\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        return dedent(match.group(1)).strip()

    return None

import json
import multiprocessing
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from colorama import Fore, Style

from gpt_workflow.utils.code_formatter import CodeFormatter
from llm_query import FileSearchResult, FileSearchResults, MatchResult, query_symbol_service
from tools.replace_engine import LLMInstructionParser, ReplaceEngine

from . import file_utils, prompts
from .llm_wrapper import TracingModelSwitch
from .worker import _extract_code_from_response, generation_worker


class UnitTestGenerator:
    """
    Generates unit tests for Python functions based on a runtime analysis report.
    This class orchestrates the process, delegating tasks to specialized modules.
    """

    def __init__(
        self,
        model_name: str = "deepseek-r1",
        checker_model_name: str = "deepseek-checker",
        trace_llm: bool = False,
        llm_trace_dir: str = "llm_traces",
        report_path: Optional[str] = None,
        test_mode: bool = False,
    ):
        self.report_path = Path(report_path) if report_path else None
        self.model_switch = TracingModelSwitch(trace_llm=trace_llm, trace_dir=llm_trace_dir, test_mode=test_mode)
        self.formatter = CodeFormatter()
        self.engine = ReplaceEngine()
        self.generator_model_name = model_name
        self.checker_model_name = checker_model_name
        self.analysis_data: Dict[str, Any] = {}
        self.test_mode = test_mode
        # [REFACTORED] project_root is now an instance variable for better testability
        self.project_root = Path(__file__).parent.parent.parent.resolve()

    def load_and_parse_report(self) -> bool:
        """Loads and validates the analysis JSON report."""
        if not self.report_path:
            print(Fore.RED + "Error: Report path was not provided.")
            return False
        assert self.report_path.exists() and not self.report_path.is_dir()
        try:
            with self.report_path.open("r", encoding="utf-8") as f:
                self.analysis_data = json.load(f)
            return True
        except (json.JSONDecodeError, IOError) as e:
            print(Fore.RED + f"Error: Failed to load or parse report file: {e}")
            return False

    def generate(
        self,
        target_funcs: List[str],
        output_dir: str,
        auto_confirm: bool = False,
        use_symbol_service: bool = True,
        num_workers: int = 0,
    ) -> bool:
        if not target_funcs:
            print(Fore.RED + "No target functions specified.")
            return False

        print(Fore.BLUE + f"Attempting to generate tests for: {', '.join(target_funcs)}")
        all_calls = self._find_all_calls_for_targets(target_funcs)
        if not all_calls:
            print(Fore.RED + "No call records found for specified functions.")
            return False

        # --- 1. Setup Phase ---
        setup_data = self._setup_generation_environment(all_calls, use_symbol_service, output_dir, auto_confirm)
        if not setup_data:
            return False
        (
            target_file_path,
            file_content,
            symbol_context,
            output_path,
            final_class_name,
            module_to_test,
            existing_code,
        ) = setup_data

        # --- 2. Task Preparation ---
        tasks = self._prepare_generation_tasks(
            all_calls,
            target_file_path,
            file_content,
            symbol_context,
            final_class_name,
            module_to_test,
            output_path,
            existing_code,
        )

        # --- 3. Generation Phase ---
        generated_snippets = self._execute_generation_tasks(tasks, num_workers)
        if not generated_snippets:
            print(Fore.YELLOW + "No new test code was generated (all cases might be duplicates).")
            return True  # Successful, but no changes

        # --- 4. Aggregation Phase ---
        final_code = self._aggregate_code(generated_snippets, output_path, existing_code)
        if not final_code:
            print(Fore.RED + "Failed to aggregate generated code.")
            return False

        # --- 5. Finalization ---
        return self._write_final_code(output_path, final_code, auto_confirm)

    def _find_all_calls_for_targets(self, target_funcs: List[str]) -> Dict[str, List[Dict]]:
        target_set = set(target_funcs)
        calls_by_func = defaultdict(list)
        frame_id_seen = set()

        def _recursive_search(record: Dict):
            if (
                isinstance(record, dict)
                and record.get("func_name") in target_set
                and record["frame_id"] not in frame_id_seen
            ):
                frame_id_seen.add(record["frame_id"])
                calls_by_func[record["func_name"]].append(record)
            for event in record.get("events", []):
                if event.get("type") == "call":
                    _recursive_search(event.get("data"))

        for funcs_data in self.analysis_data.values():
            for records in funcs_data.values():
                for record in records:
                    _recursive_search(record)
        return {f: calls for f, calls in calls_by_func.items() if calls}

    def _setup_generation_environment(
        self, all_calls_by_func: Dict, use_symbol_service: bool, output_dir: str, auto_confirm: bool
    ) -> Optional[Tuple]:
        first_func = next(iter(all_calls_by_func))
        target_file_path = Path(all_calls_by_func[first_func][0]["original_filename"])
        if not target_file_path.is_absolute():
            target_file_path = (self.project_root / target_file_path).resolve()

        symbol_context, file_content = None, None
        if use_symbol_service:
            print(Fore.CYAN + "\nUsing symbol service to gather precise code context...")
            all_calls_flat = [call for calls in all_calls_by_func.values() for call in calls]
            symbol_context = self._get_symbols_for_calls(all_calls_flat)
        if not symbol_context:
            file_content = file_utils.read_file_content(target_file_path)
            if file_content is None:
                return None

        final_file_name, final_class_name = self._get_user_confirmed_names(
            str(target_file_path), list(all_calls_by_func.keys()), file_content, auto_confirm
        )
        if not (final_file_name and final_class_name):
            return None

        output_path = file_utils.validate_and_resolve_path(output_dir, final_file_name)
        if not output_path:
            return None

        module_to_test = file_utils.get_module_path(target_file_path, self.project_root)
        if not module_to_test:
            return None

        # [NEW] Check for existing file for incremental mode
        existing_code = file_utils.read_file_content(output_path)
        if existing_code:
            print(Fore.MAGENTA + f"File '{output_path}' exists. Activating INCREMENTAL mode.")

        return (
            target_file_path,
            file_content,
            symbol_context,
            output_path,
            final_class_name,
            module_to_test,
            existing_code,
        )

    def _get_user_confirmed_names(
        self, file_path_str: str, target_funcs: List[str], file_content: Optional[str], auto_confirm: bool
    ) -> Tuple[Optional[str], Optional[str]]:
        prompt = prompts.build_suggestion_prompt(file_path_str, target_funcs, file_content)
        print(Fore.CYAN + f"Querying LLM ({self.checker_model_name}) for file and class name suggestions...")
        response_text = self.model_switch.query(self.checker_model_name, prompt)
        json_str = _extract_code_from_response(response_text)
        try:
            data = json.loads(json_str) if json_str else {}
            suggested_file, suggested_class = data.get("file_name"), data.get("class_name")
            if not (suggested_file and suggested_class):
                raise ValueError("Missing names")
        except (json.JSONDecodeError, ValueError):
            print(Fore.RED + "Could not parse suggestions from LLM.")
            return None, None

        print(Fore.GREEN + Style.BRIGHT + "\nLLM Suggestions:")
        print(f"  - Suggested File Name: {suggested_file}\n  - Suggested Class Name: {suggested_class}")
        if auto_confirm:
            print(Fore.YELLOW + "Auto-confirming suggestions.")
            return suggested_file, suggested_class

        file_input = input(f"Enter file name or press Enter for default [{suggested_file}]: ").strip()
        class_input = input(f"Enter class name or press Enter for default [{suggested_class}]: ").strip()
        return file_input or suggested_file, class_input or suggested_class

    def _get_symbols_for_calls(self, all_calls: List[Dict]) -> Optional[Dict[str, Dict]]:
        locations = set()
        for record in all_calls:
            if "original_filename" in record and "original_lineno" in record:
                locations.add((record["original_filename"], record["original_lineno"]))
            for event in record.get("events", []):
                if event.get("type") == "call":
                    data = event.get("data", {})
                    if "original_filename" in data and "original_lineno" in data:
                        locations.add((data["original_filename"], data["original_lineno"]))
        if not locations:
            return None

        file_to_lines = defaultdict(list)
        for filename, lineno in locations:
            if isinstance(filename, str) and isinstance(lineno, int):
                file_to_lines[filename].append(lineno)

        search_results = FileSearchResults(
            results=[
                FileSearchResult(file_path=f, matches=[MatchResult(line=l, column_range=(0, 0), text="") for l in ls])
                for f, ls in file_to_lines.items()
            ]
        )

        if not search_results.results:
            return None
        print(Fore.CYAN + f"Querying symbol service for {len(locations)} unique locations...")
        symbol_results = query_symbol_service(search_results, 128 * 1024)
        if isinstance(symbol_results, dict):
            print(Fore.GREEN + f"Successfully retrieved {len(symbol_results)} symbols.")
            return symbol_results
        return None

    def _prepare_generation_tasks(
        self,
        all_calls_by_func,
        target_file_path,
        file_content,
        symbol_context,
        test_class_name,
        module_to_test,
        output_path,
        existing_code,
    ) -> List[Dict]:
        tasks = []
        for target_func, call_records in all_calls_by_func.items():
            for i, call_record in enumerate(call_records):
                tasks.append(
                    {
                        "case_number": len(tasks) + 1,
                        "target_func": target_func,
                        "call_record": call_record,
                        "total_calls": len(call_records),
                        "call_index": i + 1,
                        "file_path": str(target_file_path),
                        "file_content": file_content,
                        "symbol_context": symbol_context,
                        "test_class_name": test_class_name,
                        "module_to_test": module_to_test,
                        "project_root_path": self.project_root,
                        "output_file_abs_path": output_path.resolve(),
                        "generator_model_name": self.generator_model_name,
                        "checker_model_name": self.checker_model_name,
                        "trace_llm": self.model_switch.trace_llm,
                        "trace_dir": self.model_switch.trace_run_dir.parent
                        if self.model_switch.trace_run_dir
                        else None,
                        "test_mode": self.test_mode,
                        "existing_code": existing_code,
                    }
                )
        return tasks

    def _execute_generation_tasks(self, tasks: List[Dict], num_workers: int) -> List[str]:
        if not tasks:
            return []
        use_parallel = num_workers > 1 and len(tasks) > 1
        executor = "parallel" if use_parallel else "serial"
        print(Fore.MAGENTA + f"\nStarting {executor} test case generation...")
        if use_parallel:
            with multiprocessing.Pool(processes=num_workers) as pool:
                results = pool.map(generation_worker, tasks)
        else:
            results = [generation_worker(task) for task in tasks]
        return [res for res in results if res is not None]

    def _aggregate_code(
        self, code_snippets: List[str], output_path: Path, existing_code: Optional[str]
    ) -> Optional[str]:
        if not code_snippets:
            return None  # No new code, so nothing to aggregate or write.

        if existing_code:
            base_code = existing_code
            snippets_to_merge = code_snippets
        else:
            base_code = code_snippets[0]
            snippets_to_merge = code_snippets[1:]

        if not snippets_to_merge:
            return base_code

        print(Fore.CYAN + f"\nMerging {len(snippets_to_merge)} new snippet(s) into the test file...")
        prompt = prompts.build_merge_prompt(base_code, snippets_to_merge, str(output_path))
        response = self.model_switch.query(self.checker_model_name, prompt)
        return _extract_code_from_response(response)

    def _write_final_code(self, output_path: Path, code: str, auto_confirm: bool) -> bool:
        if not code:
            print(Fore.YELLOW + "Final code is empty. Nothing to write.")
            return True
        try:
            print(Fore.CYAN + "\nFormatting generated code with ruff...")
            formatted_code = self.formatter.format_code(code)

            op_type = "overwrite_whole_file" if output_path.exists() else "created_file"
            if op_type == "overwrite_whole_file" and not auto_confirm:
                choice = input(Fore.CYAN + f"File '{output_path}' exists. Overwrite? [Y/n]: ").strip().lower()
                if choice == "n":
                    print(Fore.YELLOW + "Operation cancelled.")
                    return False

            op_name = op_type.replace("_", " ")
            instruction = f"[{op_name}]: {output_path}\n[start]\n{formatted_code}\n[end]"

            print(Fore.GREEN + f"Executing file operation to save tests to '{output_path}'...")
            self.engine.execute(LLMInstructionParser.parse(instruction))
            print(Fore.GREEN + Style.BRIGHT + "Unit test generation complete!")
            return True
        except Exception as e:
            print(Fore.RED + f"Failed to write final code: {e}")
            return False

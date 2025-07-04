import datetime
import json
import multiprocessing
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from colorama import Fore, Style

from debugger.tracer import trace
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
        checker_model_name: str = "deepseek-v3",
        trace_llm: bool = False,
        llm_trace_dir: str = "llm_traces",
        report_path: Optional[str] = None,
        import_map_path: Optional[str] = None,
        test_mode: bool = False,
        project_root: Optional[Path] = None,
    ):
        self.report_path = Path(report_path) if report_path else None
        self.import_map_path = Path(import_map_path) if import_map_path else None
        self.model_switch = TracingModelSwitch(trace_llm=trace_llm, trace_dir=llm_trace_dir, test_mode=test_mode)
        self.formatter = CodeFormatter()
        self.engine = ReplaceEngine()
        self.generator_model_name = model_name
        self.checker_model_name = checker_model_name
        self.analysis_data: Dict[str, Any] = {}
        self.import_map_data: Dict[str, Any] = {}
        self.test_mode = test_mode
        if project_root:
            self.project_root = project_root.resolve()
        else:
            self.project_root = Path(__file__).parent.parent.parent.resolve()

    def load_and_parse_report(self) -> bool:
        """Loads and validates the analysis JSON report."""
        if not self.report_path:
            print(Fore.RED + "Error: Report path was not provided.")
            return False
        if not self.report_path.exists() or self.report_path.is_dir():
            print(Fore.RED + f"Error: Report path '{self.report_path}' does not exist or is a directory.")
            return False
        try:
            with self.report_path.open("r", encoding="utf-8") as f:
                self.analysis_data = json.load(f)
            return True
        except (json.JSONDecodeError, IOError) as e:
            print(Fore.RED + f"Error: Failed to load or parse report file: {e}")
            return False

    def load_import_map(self) -> bool:
        """
        Loads the import map JSON file.
        This provides context on imported symbols for more accurate mocking.
        """
        # Infer path from report_path if not provided explicitly
        path_to_load = self.import_map_path
        if not path_to_load and self.report_path:
            path_to_load = self.report_path.parent / "import_map.json"

        if not path_to_load or not path_to_load.exists():
            print(
                Fore.YELLOW
                + "Warning: import_map.json not found. Proceeding without specific import context for mocking."
            )
            return True  # Not a fatal error

        try:
            with path_to_load.open("r", encoding="utf-8") as f:
                self.import_map_data = json.load(f)
            print(Fore.GREEN + f"Successfully loaded import map from: {path_to_load}")
            return True
        except (json.JSONDecodeError, IOError) as e:
            print(Fore.YELLOW + f"Warning: Found but failed to load or parse import map file '{path_to_load}': {e}")
            return True  # Not a fatal error

    # @trace(
    # target_files=["*.py"],
    # enable_var_trace=True,
    # report_name="unittest_generator.html",
    # ignore_self=False,
    # ignore_system_paths=True,
    # disable_html=True,
    # source_base_dir=Path(__file__).parent.parent,
    # )
    def generate(
        self,
        target_funcs: List[str],
        output_dir: str,
        auto_confirm: bool = False,
        use_symbol_service: bool = True,
        num_workers: int = 0,
        target_file: Optional[str] = None,
    ) -> bool:
        """
        [REFACTORED] Groups functions by file and generates tests for each file.
        """
        if not self.load_and_parse_report():
            return False
        self.load_import_map()  # Load import map, warnings on failure

        if not target_funcs:
            print(Fore.RED + "No target functions specified.")
            return False

        print(Fore.CYAN + f"Finding call records for {len(target_funcs)} target function(s)...")
        # Pass target_file to constrain the search and avoid ambiguity.

        all_calls_by_func = self._find_all_calls_for_targets(target_funcs, target_file)

        target_set = set(target_funcs)
        found_targets = set()
        if all_calls_by_func:
            for fq_name in all_calls_by_func.keys():
                # Check for full match or if any part of FQN is in targets
                name_parts = fq_name.split(".")
                found_targets.update(target_set.intersection(set(name_parts)))
                if fq_name in target_set:
                    found_targets.add(fq_name)

        missing_funcs = target_set - found_targets

        if not all_calls_by_func:
            print(Fore.RED + "No call records found for ANY of the specified functions in the report.")
            return False
        if missing_funcs:
            print(Fore.YELLOW + f"Warning: No call records found for: {', '.join(sorted(list(missing_funcs)))}")

        calls_by_file = self._group_calls_by_file(all_calls_by_func)

        overall_success = True
        for i, (file_path_str, funcs_in_file) in enumerate(calls_by_file.items()):
            print(Fore.BLUE + Style.BRIGHT + f"\n--- Processing File {i + 1}/{len(calls_by_file)}: {file_path_str} ---")
            calls_for_this_file = {func: all_calls_by_func[func] for func in funcs_in_file}

            success = self._generate_tests_for_file(
                calls_for_this_file,
                output_dir,
                auto_confirm,
                use_symbol_service,
                num_workers,
            )
            if not success:
                overall_success = False
        return overall_success

    def re_merge_from_directory(self, session_dir_path: str, auto_confirm: bool) -> bool:
        """[NEW] Re-runs the merge step from a session cache directory."""
        session_dir = Path(session_dir_path)
        if not session_dir.is_dir():
            print(Fore.RED + f"Error: Session directory not found at '{session_dir}'")
            return False

        metadata_path = session_dir / "metadata.json"
        if not metadata_path.exists():
            print(Fore.RED + f"Error: 'metadata.json' not found in '{session_dir}'. Cannot proceed with re-merge.")
            return False

        try:
            with metadata_path.open("r", encoding="utf-8") as f:
                metadata = json.load(f)
            output_path = Path(metadata["output_path"])

            # Load guidance, with a fallback for older metadata files
            generation_guidance = metadata.get("generation_guidance")
            if not generation_guidance:
                print(Fore.YELLOW + "Warning: 'generation_guidance' not found in metadata. Reconstructing...")
                module_to_test = metadata.get("module_to_test")
                test_class_name = metadata.get("test_class_name")
                import_context = metadata.get("import_context")

                if not (module_to_test and test_class_name):
                    print(
                        Fore.RED
                        + "Error: Cannot reconstruct guidance. Missing 'module_to_test' or 'test_class_name' in metadata."
                    )
                    return False

                existing_code = file_utils.read_file_content(output_path)
                generation_guidance = prompts.build_generation_guidance(
                    module_to_test=module_to_test,
                    test_class_name=test_class_name,
                    existing_code=existing_code,
                    import_context=import_context,
                )
                print(Fore.GREEN + "Successfully reconstructed generation guidance.")

        except (json.JSONDecodeError, KeyError) as e:
            print(Fore.RED + f"Error: Failed to read or parse metadata: {e}")
            return False

        snippet_paths = sorted(session_dir.glob("*_snippet.py"))
        if not snippet_paths:
            print(Fore.YELLOW + f"Warning: No test snippets found in '{session_dir}'. Nothing to merge.")
            return True

        print(Fore.CYAN + f"Found {len(snippet_paths)} snippets in '{session_dir}' to merge.")
        snippets = [p.read_text(encoding="utf-8") for p in snippet_paths]

        existing_code = file_utils.read_file_content(output_path)
        if existing_code:
            print(Fore.MAGENTA + f"File '{output_path}' exists. Merging new snippets into it.")
        else:
            print(Fore.MAGENTA + f"File '{output_path}' does not exist. Creating new file from snippets.")

        final_code = self._aggregate_code(snippets, output_path, existing_code, generation_guidance)
        if not final_code:
            print(Fore.RED + "Aggregation failed during re-merge.")
            return False

        return self._write_final_code(output_path, final_code, auto_confirm)

    def _filter_duplicate_code_paths(self, calls_by_func: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
        """
        [NEW] Filters call records to keep only one record for each unique code path.
        A code path is defined as the sequence of line numbers executed within the function.
        This prevents generating redundant tests for calls that follow the same execution logic.
        """
        filtered_calls = defaultdict(list)
        print(Fore.CYAN + "\nFiltering call records to find unique code paths...")

        for func_name, records in calls_by_func.items():
            seen_paths = set()
            for record in records:
                # The code path is defined by the sequence of executed line numbers.
                code_path_signature = tuple(
                    event["data"]["line_no"]
                    for event in record.get("events", [])
                    if event.get("type") == "line" and "data" in event and "line_no" in event["data"]
                )

                if code_path_signature not in seen_paths:
                    seen_paths.add(code_path_signature)
                    filtered_calls[func_name].append(record)

        # Log the result of filtering for each function
        for func_name in calls_by_func:
            original_count = len(calls_by_func[func_name])
            filtered_count = len(filtered_calls.get(func_name, []))
            if filtered_count < original_count:
                print(
                    Fore.GREEN
                    + f"De-duplication for '{func_name}': "
                    + f"Filtered {original_count} calls down to {filtered_count} unique code paths."
                )
            else:
                print(
                    Fore.GREEN
                    + f"De-duplication for '{func_name}': "
                    + f"Found {filtered_count} unique calls, no path-based duplicates were detected."
                )

        return dict(filtered_calls)

    def _group_calls_by_file(self, all_calls_by_func: Dict[str, List[Dict]]) -> Dict[str, List[str]]:
        """Groups functions by their original filename."""
        calls_by_file = defaultdict(list)
        for func_name, calls in all_calls_by_func.items():
            if not calls:
                continue
            file_path = calls[0].get("original_filename")
            if file_path:
                calls_by_file[file_path].append(func_name)
        return calls_by_file

    def _generate_tests_for_file(
        self,
        calls_for_file: Dict[str, List[Dict]],
        output_dir: str,
        auto_confirm: bool,
        use_symbol_service: bool,
        num_workers: int,
    ) -> bool:
        """Worker method to generate tests for a single file's functions."""
        target_funcs_for_file = list(calls_for_file.keys())
        print(Fore.BLUE + f"Attempting to generate tests for: {', '.join(target_funcs_for_file)}")

        if not calls_for_file:
            print(Fore.RED + "No call records found for specified functions in this file.")
            return False

        # [MODIFIED] Add de-duplication step based on code path
        calls_for_file = self._filter_duplicate_code_paths(calls_for_file)

        # After filtering, check if any calls remain
        if not any(calls_for_file.values()):
            print(
                Fore.YELLOW
                + "No unique, traceable call records found for specified functions in this file after de-duplication."
            )
            return True  # Not a failure, just nothing to do.

        setup_data = self._setup_generation_environment(calls_for_file, use_symbol_service, output_dir, auto_confirm)
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
            session_dir,
            generation_guidance,
            import_context,
        ) = setup_data

        tasks = self._prepare_generation_tasks(
            calls_for_file,
            target_file_path,
            file_content,
            symbol_context,
            final_class_name,
            module_to_test,
            output_path,
            existing_code,
            import_context,
        )

        generated_snippets = self._execute_generation_tasks(tasks, num_workers)
        if not generated_snippets:
            print(Fore.YELLOW + "No new test code was generated (all cases might be duplicates or failed).")
            return True

        self._save_snippets_to_cache(generated_snippets, session_dir)

        final_code = self._aggregate_code(generated_snippets, output_path, existing_code, generation_guidance)
        if not final_code:
            print(Fore.RED + "Failed to aggregate generated code.")
            print(Fore.YELLOW + f"Intermediate snippets are saved in: {session_dir}")
            print(Fore.YELLOW + f"You can try to re-run the merge with: --re-merge-from '{session_dir}'")
            return False

        return self._write_final_code(output_path, final_code, auto_confirm)

    def _find_all_calls_for_targets(
        self, target_funcs: List[str], target_file: Optional[str] = None
    ) -> Dict[str, List[Dict]]:
        """
        [REVISED] Finds all call records for the target functions. If a target_file is provided,
        the search is constrained to that file to resolve ambiguities with common function names.
        """
        target_set = set(target_funcs)
        calls_by_func = defaultdict(list)
        frame_id_seen = set()
        COMMON_METHODS_REQUIRING_CONTEXT = {"__init__", "__new__", "__call__", "__str__", "__repr__"}

        def _recursive_search(record: Dict):
            nonlocal frame_id_seen
            if not isinstance(record, dict):
                return

            func_name = record.get("func_name")
            frame_id = record.get("frame_id")

            if func_name and frame_id and frame_id not in frame_id_seen:
                is_match = False
                # Rule 1: Direct match of the full qualified name is always accepted.
                if func_name in target_set:
                    is_match = True
                else:
                    name_parts = func_name.split(".")
                    intersection = set(name_parts).intersection(target_set)

                    if intersection:
                        # Rule 2: A match is valid if it includes any non-ambiguous name part.
                        if intersection - COMMON_METHODS_REQUIRING_CONTEXT:
                            is_match = True
                        # Rule 3: If only ambiguous names match, require explicit context (parent class must be a target).
                        else:
                            for i, part in enumerate(name_parts):
                                if part in intersection and i > 0:
                                    parent_class_or_module = name_parts[i - 1]
                                    if parent_class_or_module in target_set:
                                        is_match = True
                                        break
                if is_match:
                    frame_id_seen.add(frame_id)
                    calls_by_func[func_name].append(record)

            # Continue search in sub-calls
            for event in record.get("events", []):
                if event.get("type") == "call" and isinstance(event.get("data"), dict):
                    _recursive_search(event.get("data"))

        # Determine the search scope based on the provided target_file to avoid ambiguity.
        search_scope = {}
        if target_file:
            target_path = Path(target_file)
            if target_path.is_absolute():
                target_path = Path(target_file).relative_to(self.project_root)
            target_file_str = str(target_path)
            if target_file_str in self.analysis_data:
                search_scope = {target_file_str: self.analysis_data[target_file_str]}
                print(Fore.GREEN + f"Search for call records constrained to file: {target_file_str}")
            else:
                print(
                    Fore.YELLOW
                    + f"Warning: Target file '{target_file_str}' not found in report keys. Searching all files."
                )
                search_scope = self.analysis_data
        else:
            search_scope = self.analysis_data

        # Iterate over the determined (and possibly constrained) scope.
        # The analysis data structure is {file_path: {entry_func_name: [call_records]}}
        for file_path, file_data in search_scope.items():
            if isinstance(file_data, dict):
                for func_records in file_data.values():
                    if isinstance(func_records, list):
                        for record in func_records:
                            _recursive_search(record)

        if target_file and not calls_by_func:
            print(
                Fore.YELLOW + f"Warning: No call records were found for any target functions in file '{target_file}'. "
                "The functions may not have been executed during tracing or the names are incorrect."
            )

        return {f: calls for f, calls in calls_by_func.items() if calls}

    def _setup_generation_environment(
        self, all_calls_by_func: Dict, use_symbol_service: bool, output_dir: str, auto_confirm: bool
    ) -> Optional[Tuple]:
        """[REFACTORED] Sets up context and saves metadata including generation guidance."""
        first_func = next(iter(all_calls_by_func))
        target_file_path = Path(all_calls_by_func[first_func][0]["original_filename"])
        if not target_file_path.is_absolute():
            target_file_path = (self.project_root / target_file_path).resolve()

        # Get import context for the target file from the loaded import map.
        import_context = self.import_map_data.get(str(target_file_path))
        if import_context:
            print(Fore.GREEN + f"Found import context for '{target_file_path}'.")

        symbol_context, file_content = None, None
        if use_symbol_service:
            print(Fore.CYAN + "\nUsing symbol service to gather precise code context...")
            all_calls_flat = [call for calls in all_calls_by_func.values() for call in calls]
            symbol_context = self._get_symbols_for_calls(all_calls_flat)
        if not symbol_context:
            if use_symbol_service:
                print(Fore.YELLOW + "Symbol service did not return context. Falling back to full file content.")
            file_content = file_utils.read_file_content(target_file_path)
            if file_content is None:
                print(Fore.RED + f"Could not read file content for '{target_file_path}'.")
                return None

        target_funcs = list(all_calls_by_func.keys())
        final_file_name, final_class_name = self._get_user_confirmed_names(
            str(target_file_path), target_funcs, file_content, auto_confirm
        )
        if not (final_file_name and final_class_name):
            return None

        output_path = file_utils.validate_and_resolve_path(output_dir, final_file_name)
        if not output_path:
            return None

        module_to_test = file_utils.get_module_path(target_file_path, self.project_root)
        if not module_to_test:
            return None

        existing_code = file_utils.read_file_content(output_path)
        if existing_code:
            print(Fore.MAGENTA + f"File '{output_path}' exists. Activating INCREMENTAL mode.")

        # Create generation guidance, which is consistent for the whole file.
        generation_guidance = prompts.build_generation_guidance(
            module_to_test=module_to_test,
            test_class_name=final_class_name,
            existing_code=existing_code,
            import_context=import_context,
        )

        # Create session dir and save metadata
        session_dir_name = f"{output_path.stem}.{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.cache"
        session_dir = output_path.parent / session_dir_name
        session_dir.mkdir(parents=True, exist_ok=True)
        print(Fore.CYAN + f"Session cache directory created at: {session_dir}")

        metadata = {
            "output_path": str(output_path.resolve()),
            "test_class_name": final_class_name,
            "module_to_test": module_to_test,
            "generation_guidance": generation_guidance,
            "import_context": import_context,
        }
        with (session_dir / "metadata.json").open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return (
            target_file_path,
            file_content,
            symbol_context,
            output_path,
            final_class_name,
            module_to_test,
            existing_code,
            session_dir,
            generation_guidance,
            import_context,
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
            return "test_generated_file.py", "TestGeneratedClass"

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
        if isinstance(symbol_results, dict) and symbol_results:
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
        import_context,
    ) -> List[Dict]:
        tasks = []
        is_incremental = existing_code is not None
        flat_call_list = []
        for target_func, call_records in all_calls_by_func.items():
            for i, call_record in enumerate(call_records):
                flat_call_list.append(
                    {
                        "target_func": target_func,
                        "call_record": call_record,
                        "call_index": i + 1,
                        "total_calls_for_func": len(call_records),
                    }
                )

        for i, call_info in enumerate(flat_call_list):
            tasks.append(
                {
                    "case_number": i + 1,
                    "target_func": call_info["target_func"],
                    "call_record": call_info["call_record"],
                    "total_calls": len(flat_call_list),
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
                    "trace_dir": self.model_switch.trace_run_dir.parent if self.model_switch.trace_run_dir else None,
                    "test_mode": self.test_mode,
                    "existing_code": existing_code,
                    "is_incremental": is_incremental,
                    "import_context": import_context,
                }
            )
        return tasks

    def _execute_generation_tasks(self, tasks: List[Dict], num_workers: int) -> List[str]:
        if not tasks:
            return []
        # Clamp num_workers to be at most the number of tasks
        effective_workers = min(num_workers, len(tasks)) if num_workers > 0 else 0

        use_parallel = effective_workers > 1
        executor = f"parallel ({effective_workers} workers)" if use_parallel else "serial"
        print(Fore.MAGENTA + f"\nStarting {executor} test case generation for {len(tasks)} tasks...")
        if use_parallel:
            with multiprocessing.Pool(processes=effective_workers) as pool:
                results = pool.map(generation_worker, tasks)
        else:
            results = [generation_worker(task) for task in tasks]
        return [res for res in results if res is not None]

    def _save_snippets_to_cache(self, snippets: List[str], session_dir: Path):
        """[NEW] Saves generated code snippets to the session cache directory."""
        if not snippets:
            return
        for i, snippet in enumerate(snippets):
            snippet_path = session_dir / f"{i + 1:03d}_snippet.py"
            snippet_path.write_text(snippet, encoding="utf-8")
        print(Fore.GREEN + f"Saved {len(snippets)} intermediate snippets to: {session_dir}")

    def _aggregate_code(
        self,
        code_snippets: List[str],
        output_path: Path,
        existing_code: Optional[str],
        generation_guidance: str,
    ) -> Optional[str]:
        """[REFACTORED] Aggregates new code into existing code using a consistent merge prompt."""
        if not code_snippets:
            return existing_code

        base_code: str
        snippets_to_merge: List[str]

        if existing_code:
            # Mode 1: Merge new snippets into an existing file.
            is_incremental = all("def test_" in s.lstrip() for s in code_snippets)
            mode_desc = "method(s)" if is_incremental else "test file(s)"
            print(Fore.CYAN + f"\nMerging {len(code_snippets)} new {mode_desc} into existing test file...")
            base_code = existing_code
            snippets_to_merge = code_snippets
        else:
            # Mode 2: No existing file. Use the first snippet as a base.
            if len(code_snippets) == 1:
                return code_snippets[0]  # No merge needed, just return the single file.

            base_code = code_snippets[0]
            snippets_to_merge = code_snippets[1:]
            print(Fore.CYAN + f"\nMerging {len(snippets_to_merge)} new test file(s) into a base test file...")

        if not snippets_to_merge:
            return base_code  # Nothing to merge, return the base as is.

        prompt = prompts.build_merge_prompt(
            existing_code=base_code,
            new_code_snippets=snippets_to_merge,
            output_path=str(output_path),
            generation_guidance=generation_guidance,
        )

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
                choice = (
                    input(Fore.YELLOW + f"File '{output_path}' exists. Overwrite? [Y/n]: " + Style.RESET_ALL)
                    .strip()
                    .lower()
                )
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

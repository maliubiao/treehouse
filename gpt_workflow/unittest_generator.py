import argparse
import sys
from pathlib import Path

from colorama import Fore, Style


def parse_args():
    """Parses command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate Unit Tests from a Call Analysis Report or re-merge from a cache.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Group for the main generation workflow
    gen_group = parser.add_argument_group("Generation Mode", "Options for generating new tests from a report")
    gen_group.add_argument(
        "--report-file",
        help="Path to the call_analysis_report.json file generated by the tracer.",
    )
    gen_group.add_argument(
        "--target-file",
        help="Path to the source file containing the target functions. Use this to resolve "
        "ambiguities when function names are common (e.g., '__init__').",
    )
    gen_group.add_argument(
        "--target-functions",
        nargs="+",
        help="One or more names of the functions to generate tests for.",
    )

    # Group for the re-merge workflow
    remerge_group = parser.add_argument_group("Re-Merge Mode", "Options for re-merging from a previous run")
    remerge_group.add_argument(
        "--re-merge-from",
        metavar="SESSION_DIR",
        help="Path to a session cache directory to re-run the merge step. "
        "If this is used, generation mode arguments are ignored.",
    )

    # Common options for both modes
    common_group = parser.add_argument_group("Common Options", "Options applicable to all modes")
    common_group.add_argument(
        "--output-dir",
        default="generated_tests",
        help="Directory to save the generated test file(s). Default: 'generated_tests'",
    )
    common_group.add_argument(
        "--project-root",
        default=str(Path.cwd()),
        help="Path to the project root directory for resolving module imports. Defaults to the current working directory.",
    )
    common_group.add_argument(
        "--model",
        default="deepseek-r1",
        help="Specify the main language model for test generation (e.g., deepseek-r1, gpt-4).",
    )
    common_group.add_argument(
        "--checker-model",
        default="deepseek-v3",
        help="Specify the model for utility tasks like suggesting names "
        "and merging files. Defaults to a faster/cheaper model.",
    )
    common_group.add_argument(
        "--use-symbol-service",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable using the symbol service to fetch precise code context. "
        "Use --no-use-symbol-service to disable. (default: enabled)",
    )
    common_group.add_argument(
        "-y",
        "--auto-confirm",
        action="store_true",
        help="Automatically confirm all interactive prompts, such as file/class name suggestions and overwrite choices.",
    )
    common_group.add_argument(
        "--trace-llm",
        action="store_true",
        help="Enable logging of LLM prompts and responses to a directory. (Default: disabled)",
    )
    common_group.add_argument(
        "--llm-trace-dir",
        default="llm_traces",
        help="Directory to save LLM traces if --trace-llm is enabled. (Default: 'llm_traces')",
    )
    common_group.add_argument(
        "--num-workers",
        type=int,
        default=0,
        help="Number of worker processes for parallel test generation. Default: 0 (serial execution). "
        "Set to > 1 for parallel.",
    )
    return parser.parse_args()


def main():
    """Main entry point for the unit test generator CLI."""
    args = parse_args()
    parser = argparse.ArgumentParser()  # For error reporting

    # Instantiate the generator, which is needed for both modes
    from gpt_workflow.unittester import UnitTestGenerator

    generator = UnitTestGenerator(
        report_path=args.report_file,
        model_name=args.model,
        checker_model_name=args.checker_model,
        trace_llm=args.trace_llm,
        llm_trace_dir=args.llm_trace_dir,
        project_root=Path(args.project_root),
    )

    if args.re_merge_from:
        # --- Re-Merge Mode ---
        print(Fore.MAGENTA + Style.BRIGHT + "\nStarting Unit Test Re-Merge Workflow")
        print(Fore.MAGENTA + "=" * 50)
        print(f"{'Session Directory:':<20} {args.re_merge_from}")
        print(f"{'Checker Model:':<20} {args.checker_model}")
        if args.auto_confirm:
            print(f"{'Auto Confirm:':<20} {Fore.YELLOW}Enabled{Style.RESET_ALL}")
        print(Fore.MAGENTA + "=" * 50 + Style.RESET_ALL)

        success = generator.re_merge_from_directory(
            session_dir_path=args.re_merge_from,
            auto_confirm=args.auto_confirm,
        )
        if not success:
            sys.exit(1)

    else:
        # --- Generation Mode ---
        if not args.report_file or not args.target_functions:
            argparse.ArgumentParser(
                prog=sys.argv[0],
                description="Generate Unit Tests from a Call Analysis Report.",
            ).error("--report-file and --target-functions are required for generation mode.")

        num_workers = args.num_workers
        if num_workers < 0:
            print(Fore.YELLOW + "num_workers cannot be negative, setting to 0 (serial).")
            num_workers = 0

        print(Fore.BLUE + Style.BRIGHT + "\nStarting Unit Test Generation Workflow")
        print(Fore.BLUE + "=" * 50)
        print(f"{'Report File:':<20} {args.report_file}")
        if args.target_file:
            print(f"{'Target File:':<20} {args.target_file}")
        print(f"{'Project Root:':<20} {args.project_root}")
        print(f"{'Target Functions:':<20} {', '.join(args.target_functions)}")
        print(f"{'Output Directory:':<20} {args.output_dir}")
        print(f"{'Generator Model:':<20} {args.model}")
        print(f"{'Checker Model:':<20} {args.checker_model}")
        print(f"{'Symbol Service:':<20} {'Enabled' if args.use_symbol_service else 'Disabled'}")
        print(f"{'Parallel Workers:':<20} {num_workers if num_workers > 0 else 'Serial'}")
        if args.auto_confirm:
            print(f"{'Auto Confirm:':<20} {Fore.YELLOW}Enabled{Style.RESET_ALL}")
        if args.trace_llm:
            print(f"{'LLM Tracing:':<20} {Fore.YELLOW}Enabled (dir: {args.llm_trace_dir}){Style.RESET_ALL}")
        print(Fore.BLUE + "=" * 50 + Style.RESET_ALL)

        if not generator.load_and_parse_report():
            sys.exit(1)

        success = generator.generate(
            target_funcs=args.target_functions,
            output_dir=args.output_dir,
            auto_confirm=args.auto_confirm,
            use_symbol_service=args.use_symbol_service,
            num_workers=num_workers,
            target_file=args.target_file,
        )
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    main()

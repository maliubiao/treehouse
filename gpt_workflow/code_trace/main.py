import argparse
import sys
from pathlib import Path

import yaml

from .config import TraceConfig
from .tracer import CodeTracer


def main():
    """
    改后遇到编译不过，把不过的那行，找出是哪个prompt生成, 并删除缓存, 获取到一串crc32
    python gpt_workflow/code_trace.py --lookup "thread_id_array.resize(num_threads);" --delete-matched
    #git restore 编译失败的文件,  重试，跳过crc32代表的那些符号， 不处理它们， 如果不跳过，前边删除了缓存，可以重试，不过还是有可能会失败
    python ~/code/terminal-llm/gpt_workflow/code_trace.py --file target/Process.cpp --skip-crc32 650fe38c,7d2f978c
    """
    parser = argparse.ArgumentParser(description="Trace code symbols and process them in batch")
    parser.add_argument("--file", "-f", dest="file_path", help="Path to the file to be analyzed")
    parser.add_argument("--config", "-c", dest="config_file", help="Path to the trace configuration file")
    parser.add_argument(
        "--no-cache", dest="no_cache_files", help="Comma-separated list of prompt files to not cache", default=""
    )
    parser.add_argument(
        "--parallel", dest="parallel", action="store_true", help="Process files in parallel", default=False
    )
    parser.add_argument(
        "--skip-crc32", dest="skip_crc32", help="Comma-separated list of CRC32 values to skip", default=""
    )
    parser.add_argument(
        "--lookup-string", dest="lookup_string", help="Search prompt cache for specific string and get CRC32 values"
    )
    parser.add_argument(
        "--lookup-yaml", dest="lookup_yaml", help="YAML file containing list of strings to lookup in prompt cache"
    )
    parser.add_argument(
        "--delete-matched",
        dest="delete_matched",
        action="store_true",
        help="Delete matched cache files when using --lookup-string or --lookup-yaml",
    )

    args = parser.parse_args()

    # Handle lookup operations first
    if args.lookup_string or args.lookup_yaml:
        search_strings = []
        if args.lookup_string:
            search_strings.append(args.lookup_string)
        if args.lookup_yaml:
            try:
                with open(args.lookup_yaml, "r") as f:
                    lookup_data = yaml.safe_load(f)
                    if isinstance(lookup_data, list):
                        search_strings.extend(lookup_data)
                    elif isinstance(lookup_data, dict) and "search_strings" in lookup_data:
                        search_strings.extend(lookup_data["search_strings"])
            except Exception as e:
                print(f"Error loading lookup YAML file: {str(e)}")
                sys.exit(1)

        all_results = []
        all_crc = set()
        for search_str in search_strings:
            results, crc_str = CodeTracer.lookup_prompt_cache(search_str, args.delete_matched)
            if results:
                all_results.extend(results)
                all_crc.update(crc_str.split(",") if crc_str else [])

        if all_results:
            print("\nFound matching cache entries:")
            print(f"{'CRC32':<10} | {'Filename':<30} | {'Timestamp':<20}")
            print("-" * 70)
            for entry in all_results:
                print(f"{entry['crc32']:<10} | {entry['filename']:<30} | {entry['timestamp']:<20}")

            crc_list = ",".join(all_crc)
            print(f"\nCombined CRC32 list for skipping: {crc_list}")
            print("You can use with --skip-crc32 parameter like:")
            print(f"  --skip-crc32 {crc_list}")
        else:
            print(f"No cache entries found containing the search strings")
        sys.exit(0)

    if args.config_file:
        config = TraceConfig(args.config_file)
        if args.skip_crc32:
            config.skip_crc32.update(args.skip_crc32.split(","))
        success, failed_file = config.trace_all_files(parallel=args.parallel)
        if success:
            print("All files processed successfully")
        else:
            print(f"Error processing files. Verification failed due to file: {failed_file}")
            if config.failed_files:
                print("Failed files list:", config.failed_files)
            sys.exit(1)
    elif args.file_path:
        skip_crc32 = args.skip_crc32.split(",") if args.skip_crc32 else []
        tracer = CodeTracer(args.file_path, skip_crc32=skip_crc32)
        if args.no_cache_files:
            tracer.no_cache_prompt_file = args.no_cache_files.split(",")
            print("No cache prompt files: ", tracer.no_cache_prompt_file)

        tracer.process()
    else:
        parser.error("Either --file or --config must be specified")


if __name__ == "__main__":
    main()

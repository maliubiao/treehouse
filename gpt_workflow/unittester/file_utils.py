import os
from pathlib import Path
from textwrap import dedent
from typing import Optional

from colorama import Fore


def validate_and_resolve_path(output_dir: str, filename: str) -> Optional[Path]:
    """Validates the filename and resolves it to a secure path within the output directory."""
    # Sanitize to prevent path traversal
    base_filename = os.path.basename(filename)
    if base_filename != filename:
        print(Fore.RED + f"Error: Invalid characters in filename '{filename}'. Path traversal is not allowed.")
        return None

    if not base_filename.startswith("test_") or not base_filename.endswith(".py"):
        print(Fore.YELLOW + f"Warning: Filename '{base_filename}' does not follow the 'test_*.py' convention.")

    try:
        output_dir_path = Path(output_dir).resolve()
        output_dir_path.mkdir(parents=True, exist_ok=True)

        output_file_path = (output_dir_path / base_filename).resolve()

        # Security check: ensure the final path is within the intended directory
        if output_dir_path != output_file_path.parent:
            error_msg = (
                f"Error: Security validation failed. The path '{output_file_path}' "
                f"is outside the allowed directory '{output_dir_path}'."
            )
            print(Fore.RED + error_msg)
            return None

        return output_file_path
    except (OSError, RuntimeError) as e:
        print(Fore.RED + f"Error resolving path: {e}")
        return None


def generate_relative_sys_path_snippet(test_file_path: Path, project_root_path: Path) -> str:
    """
    [REFACTORED] Generates a portable sys.path setup snippet based on the relative
    location of the test file to the project root, making it more robust.
    """
    try:
        test_dir = test_file_path.parent.resolve()
        proj_root = project_root_path.resolve()

        # Calculate the relative path from the test directory up to the project root.
        relative_path_to_root = os.path.relpath(proj_root, test_dir)

        # To construct the Path().parent chain, we need to go up from the test file's location.
        # The number of `parent` calls needed is the number of directory levels to go up.
        # os.path.normpath is used to resolve '.' and handle path separators correctly.
        num_parents = len(Path(os.path.normpath(relative_path_to_root)).parts)

        path_traversal = ".".join(["parent"] * num_parents)
        sys_path_code = f"project_root = Path(__file__).resolve().{path_traversal}"

    except (ValueError, OSError) as e:
        # Fallback to an absolute path if relative path calculation fails.
        print(Fore.YELLOW + f"Warning: Could not determine relative path: {e}. Falling back to absolute path.")
        sys_path_code = f"project_root = Path(r'{project_root_path.resolve()}')"

    return dedent(f"""
    import sys
    from pathlib import Path

    # Add the project root to sys.path to allow for module imports.
    # This is dynamically calculated based on the test file's location.
    {sys_path_code}
    sys.path.insert(0, str(project_root))
    """).strip()


def get_module_path(target_file_path: Path, project_root_path: Path) -> Optional[str]:
    """Get module import path relative to project root."""
    try:
        # Enhanced path compatibility handling
        target_resolved = target_file_path.resolve()
        try:
            # Attempt to calculate relative path directly
            rel_path = target_resolved.relative_to(project_root_path)
        except ValueError:
            # Fallback: handle path differences using string operations
            project_str = str(project_root_path)
            target_str = str(target_resolved)
            if target_str.startswith(project_str):
                rel_path_str = target_str[len(project_str) :].lstrip(os.path.sep)
                rel_path = Path(rel_path_str)
            else:
                raise

        module_path = rel_path.with_suffix("").as_posix().replace("/", ".")
        if module_path.endswith(".__init__"):
            module_path = module_path[:-9]
        return module_path
    except (ValueError, OSError) as e:
        error_msg = (
            f"Could not determine module path: {e}\n"
            f"Project Root: {project_root_path}\n"
            f"Target File: {target_file_path.resolve()}"
        )
        print(Fore.RED + f"Error: {error_msg}")
        return None


def read_file_content(file_path: Path) -> Optional[str]:
    """Read and return file content with error handling."""
    if not file_path.exists():
        return None
    try:
        return file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        print(Fore.RED + f"Encoding error in {file_path}: {e}")
        return None
    except Exception as e:
        print(Fore.RED + f"Failed to read file {file_path}: {e}")
        return None

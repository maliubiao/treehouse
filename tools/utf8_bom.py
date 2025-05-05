#!/usr/bin/env python3
import os
import shutil
import sys
import tempfile


def convert_to_utf8_bom(input_file, output_file=None):
    """
    Convert a file to UTF-8 with BOM encoding.
    If output_file is not specified, safely overwrite the input file using a temporary file.
    """
    try:
        # Read the input file with automatic encoding detection
        with open(input_file, "rb") as f:
            content = f.read()
            original_mode = os.stat(input_file).st_mode

        # Decode using UTF-8 (or fallback to system default if UTF-8 fails)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")  # Fallback to latin-1

        # For in-place conversion, use a temporary file
        if output_file is None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8-sig",
                dir=os.path.dirname(input_file),
                delete=False,
            ) as tmp_file:
                tmp_path = tmp_file.name
                tmp_file.write(text)

            # Preserve original file permissions
            os.chmod(tmp_path, original_mode)

            # Atomic replace operation
            shutil.move(tmp_path, input_file)
            print(f"Successfully converted {input_file} to UTF-8 with BOM (in-place)")
        else:
            with open(output_file, "w", encoding="utf-8-sig") as f:
                f.write(text)
            print(f"Successfully converted {input_file} to UTF-8 with BOM (output to {output_file})")

        return True
    except (IOError, OSError, UnicodeError) as e:
        print(f"Error converting {input_file}: {str(e)}", file=sys.stderr)
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: utf8_bom.py <input_file> [output_file]", file=sys.stderr)
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(input_file):
        print(f"Error: Input file {input_file} does not exist", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(input_file):
        print(f"Error: {input_file} is not a regular file", file=sys.stderr)
        sys.exit(1)

    success = convert_to_utf8_bom(input_file, output_file)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

#!/bin/bash

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    # Activate virtual environment
    if [ -f .venv/bin/activate ]; then
        source .venv/bin/activate
    else
        echo "Error: Virtual environment not found at .venv/bin/activate"
        exit 1
    fi
fi

# First pre-commit run
pre-commit run
if [ $? -ne 0 ]; then
    exit 1
fi

# Check for unstaged changes after first run
if git diff --exit-code >/dev/null; then
    exit 0
fi

# Stage changes
git add -u

# Second pre-commit run to verify staged files
pre-commit run
if [ $? -ne 0 ]; then
    exit 1
fi

exit 0

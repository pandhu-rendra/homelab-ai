#!/usr/bin/env sh

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_EXE="$SCRIPT_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_EXE" ]; then
    printf '%s\n' "Virtual environment not found at $PYTHON_EXE" >&2
    printf '%s\n' "Create it first with: python3 -m venv .venv" >&2
    exit 1
fi

# Run from the project directory inside a subshell so the caller's directory
# is unchanged after the application exits.
(
    cd "$SCRIPT_DIR" || exit 1
    if [ "$#" -eq 0 ]; then
        exec "$PYTHON_EXE" -m homelab_ai --demo
    fi
    exec "$PYTHON_EXE" -m homelab_ai "$@"
)
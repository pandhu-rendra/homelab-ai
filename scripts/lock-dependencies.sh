#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if command -v uv >/dev/null 2>&1; then
  uv lock
  printf '%s\n' 'Created uv.lock'
else
  printf '%s\n' 'uv is required to create the reproducible lockfile.' >&2
  exit 1
fi

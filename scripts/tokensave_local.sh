#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: tokensave_local.sh '<task>'" >&2
  exit 1
fi

prompt="$*"
prompt="${prompt/tokensave/}"
prompt="$(printf '%s' "$prompt" | sed 's/^[[:space:]:,-]*//; s/[[:space:]]*$//')"

exec /usr/bin/python3 "$(cd "$(dirname "$0")/.." && pwd)/scripts/hybrid_local_run.py" "$prompt"

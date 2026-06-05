#!/usr/bin/env bash
set -euo pipefail

OPENHANDS_BIN="${OPENHANDS_BIN:-$HOME/.local/bin/openhands}"
ARK_API_FILE="${ARK_API_FILE:-$HOME/桌面/api.txt}"
WRAPPER_BIN_DIR="${WRAPPER_BIN_DIR:-$(cd "$(dirname "$0")/bin" && pwd)}"
DEFAULT_BASE_URL="https://ark.cn-beijing.volces.com/api/coding/v3"
DEFAULT_MODEL="ark-code-latest"

workspace="${PWD}"
if [ "${1:-}" != "" ] && [ "${1#-}" = "$1" ] && [ -d "$1" ]; then
  workspace="$(cd "$1" && pwd)"
  shift
fi

if [ ! -x "$OPENHANDS_BIN" ]; then
  echo "OpenHands CLI not found at: $OPENHANDS_BIN" >&2
  exit 1
fi

if [ ! -f "$ARK_API_FILE" ]; then
  echo "Ark API file not found at: $ARK_API_FILE" >&2
  exit 1
fi

api_key="$(sed -n '1p' "$ARK_API_FILE" | tr -d '[:space:]')"
if [ -z "$api_key" ]; then
  echo "Ark API key is missing in the first line of: $ARK_API_FILE" >&2
  exit 1
fi

model="${ARK_MODEL:-$DEFAULT_MODEL}"
case "$model" in
  openai/*) ;;
  *) model="openai/$model" ;;
esac

export LLM_API_KEY="$api_key"
export LLM_BASE_URL="${ARK_BASE_URL:-$DEFAULT_BASE_URL}"
export LLM_MODEL="$model"
export LLM_DROP_PARAMS="${LLM_DROP_PARAMS:-true}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-90}"
export LLM_DISABLE_VISION="${LLM_DISABLE_VISION:-true}"
export RUNTIME="${RUNTIME:-process}"
export AGENT_ENABLE_PROMPT_EXTENSIONS="${AGENT_ENABLE_PROMPT_EXTENSIONS:-false}"
export OH_PERSISTENCE_DIR="${OH_PERSISTENCE_DIR:-$HOME/.openhands-ark}"
export PATH="$WRAPPER_BIN_DIR:$PATH"

cd "$workspace"
exec "$OPENHANDS_BIN" --override-with-envs "$@"

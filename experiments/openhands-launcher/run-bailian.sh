#!/usr/bin/env bash
set -euo pipefail

OPENHANDS_BIN="${OPENHANDS_BIN:-$HOME/.local/bin/openhands}"
OPENCLAW_ENV="${OPENCLAW_ENV:-$HOME/.openclaw/.env}"
WRAPPER_BIN_DIR="${WRAPPER_BIN_DIR:-$(cd "$(dirname "$0")/bin" && pwd)}"
DEFAULT_BASE_URL="https://coding.dashscope.aliyuncs.com/v1"
DEFAULT_MODEL="qwen3-coder-plus"

workspace="${PWD}"
if [ "${1:-}" != "" ] && [ "${1#-}" = "$1" ] && [ -d "$1" ]; then
  workspace="$(cd "$1" && pwd)"
  shift
fi

if [ ! -x "$OPENHANDS_BIN" ]; then
  echo "OpenHands CLI not found at: $OPENHANDS_BIN" >&2
  exit 1
fi

if [ ! -f "$OPENCLAW_ENV" ]; then
  echo "Bailian env file not found at: $OPENCLAW_ENV" >&2
  exit 1
fi

api_key="$(sed -n 's/^CODING_PLAN_API_KEY=//p' "$OPENCLAW_ENV" | tail -n 1 | tr -d '"' | tr -d "'")"
if [ -z "$api_key" ]; then
  echo "CODING_PLAN_API_KEY is missing in: $OPENCLAW_ENV" >&2
  exit 1
fi

model="${BAILIAN_MODEL:-$DEFAULT_MODEL}"
case "$model" in
  openai/*) ;;
  *) model="openai/$model" ;;
esac

export LLM_API_KEY="$api_key"
export LLM_BASE_URL="${BAILIAN_BASE_URL:-$DEFAULT_BASE_URL}"
export LLM_MODEL="$model"
export LLM_DROP_PARAMS="${LLM_DROP_PARAMS:-true}"
export LLM_TIMEOUT="${LLM_TIMEOUT:-90}"
export LLM_DISABLE_VISION="${LLM_DISABLE_VISION:-true}"
export RUNTIME="${RUNTIME:-process}"
export AGENT_ENABLE_PROMPT_EXTENSIONS="${AGENT_ENABLE_PROMPT_EXTENSIONS:-false}"
export OH_PERSISTENCE_DIR="${OH_PERSISTENCE_DIR:-$HOME/.openhands-bailian}"
export PATH="$WRAPPER_BIN_DIR:$PATH"

cd "$workspace"
exec "$OPENHANDS_BIN" --override-with-envs "$@"

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

import remote_agent_hybrid_job as hybrid


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path.home() / ".config" / "qiaokeli-remote-agent" / "config.env"

DEFAULTS = {
    "OPENCLAW_BIN": "/home/zhujintao/.nvm/versions/node/v22.22.0/bin/openclaw",
    "CODEX_BIN": "/home/zhujintao/.nvm/versions/node/v22.22.0/bin/codex",
    "QIAOKELI_REMOTE_AGENT_HYBRID_AGENT": "resident",
    "QIAOKELI_REMOTE_AGENT_HYBRID_TIMEOUT": "420",
    "QIAOKELI_REMOTE_AGENT_CODEX_WORKDIR": str(Path.home() / "桌面" / "数据筛选LLM"),
    "QIAOKELI_REMOTE_AGENT_MAX_OUTPUT_CHARS": "12000",
}


def load_config() -> dict[str, str]:
    values = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        for raw_line in CONFIG_PATH.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    os.environ.update(values)
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Bailian execution draft + Codex review locally")
    parser.add_argument("prompt", nargs="?", default="", help="task prompt")
    parser.add_argument("--prompt-file", default="", help="read prompt from file")
    parser.add_argument("--cwd", default="", help="working directory override")
    parser.add_argument("--agent", default="", help="OpenClaw agent override")
    parser.add_argument("--json", action="store_true", help="print full JSON result")
    return parser.parse_args()


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(errors="ignore").strip()
    if args.prompt:
        return args.prompt.strip()
    raise SystemExit("missing prompt")


def main() -> int:
    args = parse_args()
    config = load_config()
    prompt = read_prompt(args)
    runner_args = SimpleNamespace(
        openclaw_bin=config["OPENCLAW_BIN"],
        openclaw_agent=args.agent or config["QIAOKELI_REMOTE_AGENT_HYBRID_AGENT"],
        codex_bin=config["CODEX_BIN"],
        timeout=int(config["QIAOKELI_REMOTE_AGENT_HYBRID_TIMEOUT"]),
        max_output_chars=int(config["QIAOKELI_REMOTE_AGENT_MAX_OUTPUT_CHARS"]),
        workdir=str(Path(args.cwd or config["QIAOKELI_REMOTE_AGENT_CODEX_WORKDIR"]).expanduser().resolve()),
    )

    worker = hybrid.run_bailian_worker(runner_args, prompt)
    review = hybrid.run_codex_review(runner_args, prompt, worker)
    execution = hybrid.execute_approved_actions(runner_args, prompt, worker, review)
    final_reply = str(review.get("final_reply", "")).strip()
    if str(execution.get("status", "")).strip().lower() == "executed":
        final_reply = str(execution.get("summary", final_reply)).strip() or final_reply
    result = {
        "ok": True,
        "prompt": prompt,
        "result": {
            "reply": final_reply,
            "worker": worker,
            "review": review,
            "execution": execution,
            "meta": {
                "worker": str(worker.get("worker_backend", "direct_bailian")),
                "reviewer": "codex-cli",
                "mode": worker.get("mode", "general"),
                "review_profile": worker.get("classification", {}).get("review_profile", "standard"),
                "engineering_context": worker.get("engineering_context", worker.get("classification", {}).get("engineering_context", "none")),
            },
        },
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["result"]["reply"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

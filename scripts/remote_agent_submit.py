#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHARED_ROOT = Path.home() / "Sync" / "30_Projects" / "remote_agent"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit a local remote-agent command")
    parser.add_argument("--type", default="status", choices=["status", "openclaw", "codex", "hybrid", "shell", "read_file", "natural"])
    parser.add_argument("--message", default="", help="Message for openclaw or natural mode")
    parser.add_argument("--cmd", default="", help="Shell command")
    parser.add_argument("--path", default="", help="Path for read_file")
    parser.add_argument("--agent", default="", help="Optional OpenClaw agent override")
    parser.add_argument("--id", default="", help="Optional command id")
    return parser.parse_args()


def shared_root() -> Path:
    config_path = Path.home() / ".config" / "qiaokeli-remote-agent" / "config.env"
    if config_path.exists():
        for raw_line in config_path.read_text().splitlines():
            line = raw_line.strip()
            if line.startswith("QIAOKELI_REMOTE_AGENT_SHARED_ROOT="):
                return Path(line.split("=", 1)[1].strip()).expanduser().resolve()
    return DEFAULT_SHARED_ROOT


def main() -> int:
    args = parse_args()
    root = shared_root()
    commands_dir = root / "commands"
    inbox_dir = root / "inbox"
    commands_dir.mkdir(parents=True, exist_ok=True)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    command_id = args.id or f"local-{args.type}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if args.type == "natural":
        target = inbox_dir / f"{command_id}.txt"
        target.write_text((args.message or "巧克力，汇报当前主机状态。").strip() + "\n")
        print(target)
        return 0

    payload = {"id": command_id, "type": args.type}
    if args.type == "openclaw":
        payload["message"] = args.message or "汇报当前主机状态"
        if args.agent:
            payload["agent"] = args.agent
    elif args.type == "codex":
        payload["prompt"] = args.message or "Reply with one short line: codex-ok"
    elif args.type == "hybrid":
        payload["prompt"] = args.message or "先让百炼生成执行草案，再让 Codex 做最终审阅，任务是：检查当前仓库 README 有没有明显问题，并给出最终结论。"
    elif args.type == "shell":
        payload["cmd"] = args.cmd or "uname -a"
    elif args.type == "read_file":
        payload["path"] = args.path or str(PROJECT_ROOT / "README.md")

    target = commands_dir / f"{command_id}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

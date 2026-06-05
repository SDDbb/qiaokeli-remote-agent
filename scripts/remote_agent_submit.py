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
    parser.add_argument("--type", default="status", choices=["status", "openclaw", "browser", "codex", "cloud_code", "deepseek", "shell", "read_file", "android", "natural"])
    parser.add_argument("--message", default="", help="Message for openclaw or natural mode")
    parser.add_argument("--cmd", default="", help="Shell command")
    parser.add_argument("--path", default="", help="Path for read_file")
    parser.add_argument("--playbook-file", default="", help="Path to a browser or android playbook JSON file")
    parser.add_argument("--agent", default="", help="Optional OpenClaw agent override")
    parser.add_argument("--cwd", default="", help="Optional working directory override")
    parser.add_argument("--permission-mode", default="", help="Agent permission mode: default, read_only, workspace_write, full_access, or bypass")
    parser.add_argument("--android-action", default="status", help="Android action for android mode")
    parser.add_argument("--serial", default="", help="Optional adb serial for android mode")
    parser.add_argument("--target", default="", help="Optional adb connect target, such as 192.168.1.6:5555")
    parser.add_argument("--x", type=int, default=0, help="Android tap x coordinate")
    parser.add_argument("--y", type=int, default=0, help="Android tap y coordinate")
    parser.add_argument("--key", default="", help="Android keyevent name or code")
    parser.add_argument("--package", default="", help="Android package for open_app")
    parser.add_argument("--activity", default="", help="Android activity for open_app")
    parser.add_argument("--url", default="", help="URL for android open_url")
    parser.add_argument("--local-path", default="", help="Local path for android push_file/pull_file")
    parser.add_argument("--remote-path", default="", help="Android device path for push_file/pull_file")
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
    if args.cwd:
        payload["cwd"] = str(Path(args.cwd).expanduser().resolve())
    if args.permission_mode:
        payload["permission_mode"] = args.permission_mode
    if args.type == "openclaw":
        payload["message"] = args.message or "汇报当前主机状态"
        if args.agent:
            payload["agent"] = args.agent
    elif args.type == "browser":
        if args.playbook_file:
            playbook_path = Path(args.playbook_file).expanduser().resolve()
            payload["playbook"] = json.loads(playbook_path.read_text(errors="ignore"))
        else:
            payload["playbook"] = {
                "steps": [
                    {"action": "open", "url": "https://example.com"},
                    {"action": "wait", "text": "Example Domain", "timeout_ms": 10000},
                    {"action": "evaluate", "fn": "() => ({title: document.title, href: location.href})"},
                ]
            }
    elif args.type == "codex":
        payload["prompt"] = args.message or "Reply with one short line: codex-ok"
    elif args.type == "cloud_code":
        payload["prompt"] = args.message or "Reply with one short line: cloud-code-ok"
    elif args.type == "deepseek":
        payload["prompt"] = args.message or "Reply with one short line: deepseek-ok"
    elif args.type == "shell":
        payload["cmd"] = args.cmd or "uname -a"
    elif args.type == "read_file":
        payload["path"] = args.path or str(PROJECT_ROOT / "README.md")
    elif args.type == "android":
        payload["action"] = args.android_action
        if args.serial:
            payload["serial"] = args.serial
        if args.target:
            payload["target"] = args.target
        if args.message:
            payload["text"] = args.message
        if args.cmd:
            payload["shell_args"] = args.cmd
        if args.x or args.y:
            payload["x"] = args.x
            payload["y"] = args.y
        if args.key:
            payload["key"] = args.key
        if args.package:
            payload["package"] = args.package
        if args.activity:
            payload["activity"] = args.activity
        if args.url:
            payload["url"] = args.url
        if args.local_path:
            payload["local_path"] = args.local_path
        if args.remote_path:
            payload["remote_path"] = args.remote_path
        if args.playbook_file:
            payload["playbook_file"] = str(Path(args.playbook_file).expanduser().resolve())

    target = commands_dir / f"{command_id}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

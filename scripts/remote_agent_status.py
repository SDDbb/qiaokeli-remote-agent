#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


DEFAULT_SHARED_ROOT = Path.home() / "Sync" / "30_Projects" / "remote_agent"


def shared_root() -> Path:
    config_path = Path.home() / ".config" / "qiaokeli-remote-agent" / "config.env"
    if config_path.exists():
        for raw_line in config_path.read_text().splitlines():
            line = raw_line.strip()
            if line.startswith("QIAOKELI_REMOTE_AGENT_SHARED_ROOT="):
                return Path(line.split("=", 1)[1].strip()).expanduser().resolve()
    return DEFAULT_SHARED_ROOT


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def main() -> int:
    root = shared_root()
    payload = {
        "heartbeat": load(root / "status" / "heartbeat.json"),
        "last_response": load(root / "status" / "last_response.json"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

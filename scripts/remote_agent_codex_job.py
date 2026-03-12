#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "\n...[truncated]..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Background Codex job for qiaokeli remote agent")
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--response-file", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    parser.add_argument("--max-output-chars", type=int, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--input-mode", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompt = Path(args.prompt_file).read_text(errors="ignore").strip()
    response_path = Path(args.response_file)
    workdir = Path(args.workdir).expanduser().resolve()

    wrapped_prompt = (
        "Reply in concise Chinese unless the user explicitly asked otherwise. "
        "Give the final answer directly.\n\n"
        f"User task:\n{prompt}"
    )

    with tempfile.NamedTemporaryFile(prefix="remote-agent-codex-", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)

    try:
        completed = subprocess.run(
            [
                args.codex_bin,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                "--cd",
                str(workdir),
                "--output-last-message",
                str(output_path),
                wrapped_prompt,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
            check=False,
        )
        reply = output_path.read_text(errors="ignore").strip() if output_path.exists() else ""
        if completed.returncode == 0:
            payload = {
                "id": args.command_id,
                "ok": True,
                "type": "codex",
                "input_mode": args.input_mode,
                "status": "completed",
                "finished_at": now_iso(),
                "host": args.host,
                "result": {
                    "workdir": str(workdir),
                    "reply": trim_text(reply or completed.stdout.strip(), args.max_output_chars),
                    "meta": {
                        "tool": "codex-cli",
                        "timeout_seconds": args.timeout,
                        "async": True,
                    },
                },
            }
        else:
            payload = {
                "id": args.command_id,
                "ok": False,
                "type": "codex",
                "input_mode": args.input_mode,
                "status": "failed",
                "finished_at": now_iso(),
                "host": args.host,
                "error": trim_text(completed.stderr.strip() or completed.stdout.strip() or "codex command failed", args.max_output_chars),
            }
        response_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    finally:
        output_path.unlink(missing_ok=True)
        Path(args.prompt_file).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    parser = argparse.ArgumentParser(description="Background Bailian+Codex job for qiaokeli remote agent")
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--response-file", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--openclaw-bin", required=True)
    parser.add_argument("--openclaw-agent", required=True)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    parser.add_argument("--max-output-chars", type=int, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--input-mode", required=True)
    return parser.parse_args()


def parse_openclaw_text(raw: str) -> str:
    outer = json.loads(raw)
    payloads = outer.get("result", {}).get("payloads", [])
    first = payloads[0] if payloads else {}
    return str(first.get("text", "")).strip()


def parse_json_object(text: str) -> dict[str, object]:
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) >= 3:
            body = "\n".join(lines[1:-1]).strip()
    return json.loads(body)


def run_bailian_worker(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    worker_prompt = f"""You are the low-cost execution worker in a coding orchestration stack.
Return strict JSON only with this exact shape:
{{
  "task_summary": "...",
  "risk_level": "low|medium|high",
  "recommended_route": "bailian_only|bailian_then_codex|codex_only",
  "execution_draft": {{
    "goal": "...",
    "plan": ["...", "..."],
    "proposed_commands": ["..."],
    "proposed_file_changes": ["..."],
    "proposed_reply": "...",
    "risks": ["..."],
    "needs_human_confirmation": true
  }}
}}

Rules:
- language: Simplified Chinese
- do not invent local command outputs
- this is a planning and draft layer only
- do not claim code was modified
- if the task is risky, say so clearly

User task:
{prompt}
"""
    completed = subprocess.run(
        [
            args.openclaw_bin,
            "agent",
            "--agent",
            args.openclaw_agent,
            "--json",
            "--timeout",
            str(max(120, args.timeout - 90)),
            "--message",
            worker_prompt,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(150, args.timeout - 60),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "OpenClaw Bailian worker failed")
    return parse_json_object(parse_openclaw_text(completed.stdout))


def run_codex_review(args: argparse.Namespace, prompt: str, worker_output: dict[str, object]) -> dict[str, object]:
    reviewer_prompt = f"""Review the following Bailian execution draft for the user task.
Reply in strict JSON only with this exact shape:
{{
  "verdict": "approve|revise|reject",
  "final_reply": "...",
  "review_notes": ["..."],
  "safe_next_steps": ["..."]
}}

Rules:
- language: Simplified Chinese
- be concise and concrete
- do not pretend anything was executed unless the worker output proves it
- if the worker draft is weak or risky, say revise or reject
- the final reply should be what the end user should read

User task:
{prompt}

Bailian worker draft:
{json.dumps(worker_output, ensure_ascii=False, indent=2)}
"""
    with tempfile.NamedTemporaryFile(prefix="remote-agent-hybrid-codex-", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                args.codex_bin,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                "--cd",
                args.workdir,
                "--output-last-message",
                str(output_path),
                reviewer_prompt,
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
            check=False,
        )
        reply = output_path.read_text(errors="ignore").strip() if output_path.exists() else ""
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "Codex review failed")
        return parse_json_object(reply or completed.stdout.strip())
    finally:
        output_path.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    prompt = Path(args.prompt_file).read_text(errors="ignore").strip()
    response_path = Path(args.response_file)
    try:
        worker_output = run_bailian_worker(args, prompt)
        codex_review = run_codex_review(args, prompt, worker_output)
        payload = {
            "id": args.command_id,
            "ok": True,
            "type": "hybrid",
            "input_mode": args.input_mode,
            "status": "completed",
            "finished_at": now_iso(),
            "host": args.host,
            "result": {
                "workdir": str(Path(args.workdir).expanduser().resolve()),
                "reply": trim_text(str(codex_review.get("final_reply", "")).strip(), args.max_output_chars),
                "worker": worker_output,
                "review": codex_review,
                "meta": {
                    "worker": "openclaw-bailian",
                    "reviewer": "codex-cli",
                    "async": True,
                },
            },
        }
    except Exception as exc:
        payload = {
            "id": args.command_id,
            "ok": False,
            "type": "hybrid",
            "input_mode": args.input_mode,
            "status": "failed",
            "finished_at": now_iso(),
            "host": args.host,
            "error": trim_text(str(exc), args.max_output_chars),
        }
    finally:
        Path(args.prompt_file).unlink(missing_ok=True)

    response_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

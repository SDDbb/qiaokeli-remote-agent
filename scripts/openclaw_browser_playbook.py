#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a deterministic OpenClaw browser playbook")
    parser.add_argument("--playbook-file", required=True, help="Path to a JSON playbook file")
    parser.add_argument("--openclaw-bin", required=True, help="Path to the openclaw CLI")
    parser.add_argument("--timeout", type=int, default=180, help="Default subprocess timeout in seconds")
    return parser.parse_args()


def load_playbook(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(errors="ignore"))
    if isinstance(raw, list):
        raw = {"steps": raw}
    if not isinstance(raw, dict):
        raise ValueError("playbook must be a JSON object or array of steps")
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("playbook.steps must be a non-empty array")
    return raw


def run_browser_json(openclaw_bin: str, args: list[str], timeout: int) -> dict[str, Any]:
    completed = subprocess.run(
        [openclaw_bin, "browser", "--json", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "openclaw browser command failed"
        raise RuntimeError(detail)
    stdout = completed.stdout.strip()
    if not stdout:
        return {"ok": True}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {"ok": True, "raw": stdout}
    if isinstance(parsed, dict):
        return parsed
    return {"ok": True, "result": parsed}


def step_timeout(default_timeout: int, step: dict[str, Any]) -> int:
    value = int(step.get("timeout") or default_timeout)
    return max(1, value)


def resolve_target_id(step: dict[str, Any], current_target_id: str, default_target_id: str) -> str:
    target_id = str(step.get("target_id", "")).strip()
    if target_id:
        return target_id
    if current_target_id:
        return current_target_id
    return default_target_id


def add_target_id(args: list[str], target_id: str) -> list[str]:
    if target_id:
        return [*args, "--target-id", target_id]
    return args


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def select_single_tab(tabs: list[dict[str, Any]], step: dict[str, Any]) -> dict[str, Any]:
    target_id = str(step.get("target_id", "")).strip()
    url = str(step.get("url", "")).strip()
    title = str(step.get("title", "")).strip()
    url_contains = str(step.get("url_contains", "")).strip()
    title_contains = str(step.get("title_contains", "")).strip()

    matched = list(tabs)
    if target_id:
        matched = [tab for tab in matched if str(tab.get("targetId", "")).startswith(target_id)]
    if url:
        matched = [tab for tab in matched if str(tab.get("url", "")) == url]
    if title:
        matched = [tab for tab in matched if str(tab.get("title", "")) == title]
    if url_contains:
        matched = [tab for tab in matched if url_contains in str(tab.get("url", ""))]
    if title_contains:
        matched = [tab for tab in matched if title_contains in str(tab.get("title", ""))]

    if not matched:
        raise ValueError("pick_tab found no matching tab")
    if len(matched) > 1:
        sample = [
            {
                "targetId": str(tab.get("targetId", "")),
                "title": str(tab.get("title", "")),
                "url": str(tab.get("url", "")),
            }
            for tab in matched[:5]
        ]
        raise ValueError(f"pick_tab matched multiple tabs; make the selector stricter: {json.dumps(sample, ensure_ascii=False)}")
    return matched[0]


def run_step(
    openclaw_bin: str,
    step: dict[str, Any],
    default_timeout: int,
    current_target_id: str,
    default_target_id: str,
) -> tuple[dict[str, Any], str]:
    action = str(step.get("action", "")).strip().lower()
    if not action:
        raise ValueError("step missing action")

    timeout = step_timeout(default_timeout, step)
    target_id = resolve_target_id(step, current_target_id, default_target_id)

    if action == "status":
        result = run_browser_json(openclaw_bin, ["status"], timeout)
        return result, current_target_id

    if action == "tabs":
        result = run_browser_json(openclaw_bin, ["tabs"], timeout)
        return result, current_target_id

    if action == "pick_tab":
        tabs_result = run_browser_json(openclaw_bin, ["tabs"], timeout)
        tabs = tabs_result.get("tabs")
        if not isinstance(tabs, list):
            raise ValueError("tabs result is missing a tabs array")
        chosen = select_single_tab(tabs, step)
        next_target_id = str(chosen.get("targetId", "")).strip()
        return {
            "ok": True,
            "selected": chosen,
            "targetId": next_target_id,
            "matchedCount": 1,
        }, next_target_id

    if action == "focus":
        if not target_id:
            raise ValueError("focus requires target_id or a previously selected tab")
        result = run_browser_json(openclaw_bin, ["focus", target_id], timeout)
        return result, target_id

    if action == "open":
        url = first_non_empty(step.get("url"))
        if not url:
            raise ValueError("open requires url")
        result = run_browser_json(openclaw_bin, ["open", url], timeout)
        next_target_id = first_non_empty(result.get("targetId"), current_target_id)
        return result, next_target_id

    if action == "navigate":
        url = first_non_empty(step.get("url"))
        if not url:
            raise ValueError("navigate requires url")
        result = run_browser_json(openclaw_bin, add_target_id(["navigate", url], target_id), timeout)
        return result, target_id or current_target_id

    if action == "wait":
        args = ["wait"]
        selector = first_non_empty(step.get("selector"))
        if step.get("time") is not None:
            args.extend(["--time", str(step.get("time"))])
        if step.get("text") is not None:
            args.extend(["--text", str(step.get("text"))])
        if step.get("text_gone") is not None:
            args.extend(["--text-gone", str(step.get("text_gone"))])
        if step.get("url") is not None:
            args.extend(["--url", str(step.get("url"))])
        if step.get("load") is not None:
            args.extend(["--load", str(step.get("load"))])
        if step.get("fn") is not None:
            args.extend(["--fn", str(step.get("fn"))])
        if step.get("timeout_ms") is not None:
            args.extend(["--timeout-ms", str(step.get("timeout_ms"))])
        if selector:
            args.append(selector)
        result = run_browser_json(openclaw_bin, add_target_id(args, target_id), timeout)
        return result, target_id or current_target_id

    if action == "snapshot":
        args = ["snapshot"]
        if bool(step.get("efficient", True)):
            args.append("--efficient")
        if bool(step.get("interactive", False)):
            args.append("--interactive")
        if bool(step.get("labels", False)):
            args.append("--labels")
        if bool(step.get("compact", False)):
            args.append("--compact")
        if step.get("format") is not None:
            args.extend(["--format", str(step.get("format"))])
        if step.get("selector") is not None:
            args.extend(["--selector", str(step.get("selector"))])
        if step.get("frame") is not None:
            args.extend(["--frame", str(step.get("frame"))])
        if step.get("depth") is not None:
            args.extend(["--depth", str(step.get("depth"))])
        if step.get("limit") is not None:
            args.extend(["--limit", str(step.get("limit"))])
        result = run_browser_json(openclaw_bin, add_target_id(args, target_id), timeout)
        return result, target_id or current_target_id

    if action == "evaluate":
        fn = first_non_empty(step.get("fn"))
        if not fn:
            raise ValueError("evaluate requires fn")
        args = ["evaluate", "--fn", fn]
        if step.get("ref") is not None:
            args.extend(["--ref", str(step.get("ref"))])
        result = run_browser_json(openclaw_bin, add_target_id(args, target_id), timeout)
        return result, target_id or current_target_id

    if action == "click":
        ref = first_non_empty(step.get("ref"))
        if not ref:
            raise ValueError("click requires ref")
        args = ["click", ref]
        if bool(step.get("double", False)):
            args.append("--double")
        if step.get("button") is not None:
            args.extend(["--button", str(step.get("button"))])
        if step.get("modifiers") is not None:
            args.extend(["--modifiers", str(step.get("modifiers"))])
        result = run_browser_json(openclaw_bin, add_target_id(args, target_id), timeout)
        return result, target_id or current_target_id

    if action == "press":
        key = first_non_empty(step.get("key"))
        if not key:
            raise ValueError("press requires key")
        result = run_browser_json(openclaw_bin, add_target_id(["press", key], target_id), timeout)
        return result, target_id or current_target_id

    if action == "type":
        ref = first_non_empty(step.get("ref"))
        text = str(step.get("text", ""))
        if not ref:
            raise ValueError("type requires ref")
        args = ["type", ref, text]
        if bool(step.get("submit", False)):
            args.append("--submit")
        result = run_browser_json(openclaw_bin, add_target_id(args, target_id), timeout)
        return result, target_id or current_target_id

    if action == "fill":
        fields = step.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError("fill requires a non-empty fields array")
        args = ["fill", "--fields", json.dumps(fields, ensure_ascii=False)]
        result = run_browser_json(openclaw_bin, add_target_id(args, target_id), timeout)
        return result, target_id or current_target_id

    raise ValueError(f"unsupported browser action: {action}")


def main() -> int:
    args = parse_args()
    playbook_path = Path(args.playbook_file).expanduser().resolve()
    playbook = load_playbook(playbook_path)
    steps = playbook["steps"]
    default_target_id = str(playbook.get("default_target_id", "")).strip()
    current_target_id = default_target_id
    saved: dict[str, Any] = {}
    results: list[dict[str, Any]] = []

    for index, raw_step in enumerate(steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"step {index} must be a JSON object")
        action = str(raw_step.get("action", "")).strip().lower()
        try:
            result, current_target_id = run_step(
                args.openclaw_bin,
                raw_step,
                args.timeout,
                current_target_id,
                default_target_id,
            )
            save_as = str(raw_step.get("save_as", "")).strip()
            if save_as:
                saved[save_as] = result
            results.append(
                {
                    "index": index,
                    "action": action,
                    "ok": True,
                    "target_id": current_target_id,
                    "saved_as": save_as or None,
                    "result": result,
                }
            )
        except Exception as exc:
            optional = bool(raw_step.get("optional", False))
            entry = {
                "index": index,
                "action": action,
                "ok": False,
                "optional": optional,
                "error": str(exc),
            }
            results.append(entry)
            if not optional:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "playbook_file": str(playbook_path),
                            "current_target_id": current_target_id,
                            "results": results,
                            "saved": saved,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 1

    print(
        json.dumps(
            {
                "ok": True,
                "playbook_file": str(playbook_path),
                "current_target_id": current_target_id,
                "results": results,
                "saved": saved,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

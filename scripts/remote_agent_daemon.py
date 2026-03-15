#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import re


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SHARED_ROOT = Path.home() / "Sync" / "30_Projects" / "remote_agent"
CONFIG_DIR = Path.home() / ".config" / "qiaokeli-remote-agent"
CONFIG_FILE = CONFIG_DIR / "config.env"
STATE_FILE = PROJECT_ROOT / "runtime" / "state.json"

DEFAULT_CONFIG = {
    "QIAOKELI_REMOTE_AGENT_SHARED_ROOT": str(DEFAULT_SHARED_ROOT),
    "QIAOKELI_REMOTE_AGENT_POLL_SECONDS": "5",
    "QIAOKELI_REMOTE_AGENT_HEARTBEAT_SECONDS": "30",
    "QIAOKELI_REMOTE_AGENT_SHELL_TIMEOUT": "120",
    "QIAOKELI_REMOTE_AGENT_MAX_OUTPUT_CHARS": "12000",
    "QIAOKELI_REMOTE_AGENT_OPENCLAW_AGENT": "resident",
    "QIAOKELI_REMOTE_AGENT_OPENCLAW_TIMEOUT": "240",
    "OPENCLAW_BIN": "/home/zhujintao/.nvm/versions/node/v22.22.0/bin/openclaw",
    "CODEX_BIN": "/home/zhujintao/.nvm/versions/node/v22.22.0/bin/codex",
    "QIAOKELI_REMOTE_AGENT_CODEX_TIMEOUT": "300",
    "QIAOKELI_REMOTE_AGENT_CODEX_WORKDIR": str(Path.home() / "桌面" / "数据筛选LLM"),
    "QIAOKELI_REMOTE_AGENT_HYBRID_AGENT": "resident",
    "QIAOKELI_REMOTE_AGENT_HYBRID_TIMEOUT": "420",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ensure_config() -> dict[str, str]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "runtime").mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        example = PROJECT_ROOT / "config" / "config.env.example"
        CONFIG_FILE.write_text(example.read_text())
    values = dict(DEFAULT_CONFIG)
    for raw_line in CONFIG_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    os.environ.update(values)
    return values


def shared_dirs(config: dict[str, str]) -> dict[str, Path]:
    root = Path(config["QIAOKELI_REMOTE_AGENT_SHARED_ROOT"]).expanduser().resolve()
    return {
        "root": root,
        "commands": root / "commands",
        "inbox": root / "inbox",
        "responses": root / "responses",
        "status": root / "status",
        "examples": root / "examples",
    }


def ensure_shared_layout(paths: dict[str, Path]) -> None:
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"processed": {}, "last_command_id": "", "last_heartbeat_at": ""}
    try:
        data = json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {"processed": {}, "last_command_id": "", "last_heartbeat_at": ""}
    data.setdefault("processed", {})
    data.setdefault("last_command_id", "")
    data.setdefault("last_heartbeat_at", "")
    return data


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "\n...[truncated]..."


def run_cmd(args: list[str], timeout: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def service_active(unit: str) -> bool:
    completed = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "active"


def host_status() -> dict[str, Any]:
    tailscale_ip = ""
    rc, out, _err = run_cmd(["tailscale", "ip", "-4"], timeout=15)
    if rc == 0:
        tailscale_ip = out.strip().splitlines()[0] if out.strip() else ""
    return {
        "host": socket.gethostname(),
        "generated_at": now_iso(),
        "tailscale_ip": tailscale_ip,
        "tailscale_online": bool(tailscale_ip),
        "syncthing_active": service_active("syncthing.service"),
        "openclaw_gateway_active": service_active("openclaw-gateway.service"),
        "authorized_research_active": service_active("qiaokeli-authorized-research.service"),
        "remote_agent_active": service_active("qiaokeli-remote-agent.service"),
    }


def write_heartbeat(state: dict[str, Any], paths: dict[str, Path]) -> None:
    payload = host_status()
    payload["last_command_id"] = state.get("last_command_id", "")
    (paths["status"] / "heartbeat.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    state["last_heartbeat_at"] = payload["generated_at"]


def parse_openclaw_result(text: str) -> dict[str, Any]:
    outer = json.loads(text)
    payloads = outer.get("result", {}).get("payloads", [])
    first = payloads[0] if payloads else {}
    meta = outer.get("result", {}).get("meta", {}) or {}
    agent_meta = meta.get("agentMeta", {}) or {}
    return {
        "text": str(first.get("text", "")).strip(),
        "meta": {
            "duration_ms": meta.get("durationMs"),
            "provider": agent_meta.get("provider"),
            "model": agent_meta.get("model"),
            "session_id": agent_meta.get("sessionId"),
            "aborted": meta.get("aborted"),
        },
    }


def handle_openclaw(command: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    agent = str(command.get("agent") or config["QIAOKELI_REMOTE_AGENT_OPENCLAW_AGENT"])
    timeout = int(command.get("timeout") or config["QIAOKELI_REMOTE_AGENT_OPENCLAW_TIMEOUT"])
    message = str(command.get("message", "")).strip()
    if not message:
        raise ValueError("missing openclaw message")
    live_status = json.dumps(host_status(), ensure_ascii=False)
    wrapped_message = (
        "On this Fedora host, perform the task with real tools when needed. "
        "Do not guess about local state. Respond concisely in Chinese and give the final answer directly.\n\n"
        f"Live host facts you can trust:\n{live_status}\n\n"
        f"User task:\n{message}"
    )
    rc, out, err = run_cmd(
        [
            config["OPENCLAW_BIN"],
            "agent",
            "--agent",
            agent,
            "--json",
            "--timeout",
            str(timeout),
            "--message",
            wrapped_message,
        ],
        timeout=timeout + 30,
    )
    if rc != 0:
        raise RuntimeError(err.strip() or out.strip() or "openclaw command failed")
    parsed = parse_openclaw_result(out)
    return {"agent": agent, "reply": parsed["text"], "meta": parsed["meta"]}


def launch_codex_job(
    command: dict[str, Any],
    command_id: str,
    input_mode: str,
    config: dict[str, str],
    paths: dict[str, Path],
) -> dict[str, Any]:
    prompt = str(command.get("prompt") or command.get("message", "")).strip()
    if not prompt:
        raise ValueError("missing codex prompt")
    timeout = int(command.get("timeout") or config["QIAOKELI_REMOTE_AGENT_CODEX_TIMEOUT"])
    cwd = str(command.get("cwd") or config["QIAOKELI_REMOTE_AGENT_CODEX_WORKDIR"]).strip()
    workdir = Path(cwd).expanduser().resolve()
    if not workdir.exists():
        raise FileNotFoundError(str(workdir))

    prompt_path = PROJECT_ROOT / "runtime" / f"{command_id}.prompt.txt"
    prompt_path.write_text(prompt + "\n")
    response_path = paths["responses"] / f"{command_id}.json"
    job_script = PROJECT_ROOT / "scripts" / "remote_agent_codex_job.py"

    subprocess.Popen(
        [
            "/usr/bin/python3",
            str(job_script),
            "--command-id",
            command_id,
            "--prompt-file",
            str(prompt_path),
            "--response-file",
            str(response_path),
            "--workdir",
            str(workdir),
            "--codex-bin",
            config["CODEX_BIN"],
            "--timeout",
            str(timeout),
            "--max-output-chars",
            config["QIAOKELI_REMOTE_AGENT_MAX_OUTPUT_CHARS"],
            "--host",
            socket.gethostname(),
            "--input-mode",
            input_mode,
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "workdir": str(workdir),
        "reply": "Codex 任务已接受，正在后台执行。请稍后刷新同名 response 文件查看最终结果。",
        "meta": {
            "tool": "codex-cli",
            "timeout_seconds": timeout,
            "async": True,
        },
    }


def launch_hybrid_job(
    command: dict[str, Any],
    command_id: str,
    input_mode: str,
    config: dict[str, str],
    paths: dict[str, Path],
) -> dict[str, Any]:
    prompt = str(command.get("prompt") or command.get("message", "")).strip()
    if not prompt:
        raise ValueError("missing hybrid prompt")
    timeout = int(command.get("timeout") or config["QIAOKELI_REMOTE_AGENT_HYBRID_TIMEOUT"])
    workdir = Path(str(command.get("cwd") or config["QIAOKELI_REMOTE_AGENT_CODEX_WORKDIR"]).strip()).expanduser().resolve()
    if not workdir.exists():
        raise FileNotFoundError(str(workdir))

    prompt_path = PROJECT_ROOT / "runtime" / f"{command_id}.hybrid.prompt.txt"
    prompt_path.write_text(prompt + "\n")
    response_path = paths["responses"] / f"{command_id}.json"
    job_script = PROJECT_ROOT / "scripts" / "remote_agent_hybrid_job.py"
    agent = str(command.get("agent") or config["QIAOKELI_REMOTE_AGENT_HYBRID_AGENT"]).strip()

    subprocess.Popen(
        [
            "/usr/bin/python3",
            str(job_script),
            "--command-id",
            command_id,
            "--prompt-file",
            str(prompt_path),
            "--response-file",
            str(response_path),
            "--workdir",
            str(workdir),
            "--openclaw-bin",
            config["OPENCLAW_BIN"],
            "--openclaw-agent",
            agent,
            "--codex-bin",
            config["CODEX_BIN"],
            "--timeout",
            str(timeout),
            "--max-output-chars",
            config["QIAOKELI_REMOTE_AGENT_MAX_OUTPUT_CHARS"],
            "--host",
            socket.gethostname(),
            "--input-mode",
            input_mode,
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "workdir": str(workdir),
        "reply": "百炼执行层任务已接受，正在由 Bailian 产出草案并交给 Codex 审阅。请稍后刷新同名 response 文件查看最终结果。",
        "meta": {
            "tool": "bailian+codex",
            "timeout_seconds": timeout,
            "async": True,
            "review_required": True,
        },
    }


def handle_shell(command: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    cmd = str(command.get("cmd", "")).strip()
    if not cmd:
        raise ValueError("missing shell cmd")
    cwd = str(command.get("cwd", str(Path.home()))).strip()
    timeout = int(command.get("timeout") or config["QIAOKELI_REMOTE_AGENT_SHELL_TIMEOUT"])
    completed = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    limit = int(config["QIAOKELI_REMOTE_AGENT_MAX_OUTPUT_CHARS"])
    return {
        "cwd": cwd,
        "returncode": completed.returncode,
        "stdout": trim_text(completed.stdout, limit),
        "stderr": trim_text(completed.stderr, limit),
    }


def handle_read_file(command: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    raw_path = str(command.get("path", "")).strip()
    if not raw_path:
        raise ValueError("missing read_file path")
    path = Path(raw_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    limit = int(command.get("max_chars") or config["QIAOKELI_REMOTE_AGENT_MAX_OUTPUT_CHARS"])
    content = path.read_text(errors="ignore")
    return {"path": str(path), "content": trim_text(content, limit)}


def handle_status(_command: dict[str, Any], _config: dict[str, str]) -> dict[str, Any]:
    return host_status()


def process_command(command: dict[str, Any], config: dict[str, str], command_id: str, input_mode: str, paths: dict[str, Path]) -> dict[str, Any]:
    command_type = str(command.get("type", "status")).strip().lower()
    if command_type == "status":
        return handle_status(command, config)
    if command_type == "openclaw":
        return handle_openclaw(command, config)
    if command_type == "codex":
        return launch_codex_job(command, command_id, input_mode, config, paths)
    if command_type == "hybrid":
        return launch_hybrid_job(command, command_id, input_mode, config, paths)
    if command_type == "shell":
        return handle_shell(command, config)
    if command_type == "read_file":
        return handle_read_file(command, config)
    raise ValueError(f"unsupported command type: {command_type}")


def command_signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def write_response(command_id: str, payload: dict[str, Any], paths: dict[str, Path]) -> None:
    target = paths["responses"] / f"{command_id}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    (paths["status"] / "last_response.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def build_examples(paths: dict[str, Path]) -> None:
    examples = {
        "status.json": {"id": "phone-status", "type": "status"},
        "openclaw.json": {"id": "phone-openclaw", "type": "openclaw", "message": "汇报当前主机状态"},
        "codex.json": {"id": "phone-codex", "type": "codex", "prompt": "检查当前仓库 README 有没有明显问题，并直接给结论"},
        "hybrid.json": {"id": "phone-hybrid", "type": "hybrid", "prompt": "先让百炼为当前任务生成执行草案，再让 Codex 做最终审阅，任务是：检查当前仓库 README 有没有明显问题，并给出最终结论。"},
        "shell.json": {"id": "phone-shell", "type": "shell", "cmd": "uname -a"},
        "read_file.json": {"id": "phone-read-file", "type": "read_file", "path": str(Path.home() / ".openclaw" / "workspace" / "authorized_research" / "memory" / "rolling_memory.md")},
        "natural-language.txt": "巧克力，汇报当前主机状态，并告诉我 Syncthing 和 OpenClaw 是否正常。",
        "natural-codex.txt": "让 Codex 检查当前仓库 README 有没有明显问题，并直接告诉我结论。",
        "natural-hybrid.txt": "先让百炼执行，再让 Codex 审阅：检查当前仓库 README 有没有明显问题，并直接告诉我最终结论。",
    }
    for name, body in examples.items():
        target = paths["examples"] / name
        if target.exists():
            continue
        if name.endswith(".json"):
            target.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")
        else:
            target.write_text(str(body).strip() + "\n")


def iter_command_files(paths: dict[str, Path]) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted(paths["commands"].glob("*.json")):
        files.append((path, "json"))
    for path in sorted(paths["inbox"].glob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".txt", ".md"}:
            continue
        if path.stem.lower().startswith("readme"):
            continue
        files.append((path, "natural"))
    return files


def parse_command_file(path: Path, mode: str) -> dict[str, Any]:
    if mode == "json":
        return json.loads(path.read_text())
    message = path.read_text(errors="ignore").strip()
    lowered = message.lower()
    hybrid_prefix_markers = [
        r"^\s*/?hybrid[:：\s]",
        r"^\s*(先)?让\s*(百炼|bailian)",
        r"^\s*(先)?用\s*(百炼|bailian)",
    ]
    for pattern in hybrid_prefix_markers:
        if re.search(pattern, lowered, flags=re.I) and re.search(r"(codex|审阅|审查|review|复核)", lowered, flags=re.I):
            prompt = re.sub(pattern, "", message, count=1, flags=re.I).strip("：:，, \n\t")
            return {"id": path.stem, "type": "hybrid", "prompt": prompt or message}

    hybrid_anywhere_markers = [
        r"(百炼|bailian).{0,24}(codex|审阅|审查|review|复核)",
        r"(先).{0,24}(百炼|bailian).{0,40}(再).{0,24}(codex|审阅|审查|review|复核)",
    ]
    for pattern in hybrid_anywhere_markers:
        if re.search(pattern, lowered, flags=re.I):
            return {"id": path.stem, "type": "hybrid", "prompt": message}

    codex_prefix_markers = [
        r"^\s*/?codex[:：\s]",
        r"^\s*让\s*codex",
        r"^\s*调用\s*codex",
        r"^\s*请\s*codex",
        r"^\s*让\s*vscode.*codex",
        r"^\s*调用\s*vscode.*codex",
    ]
    for pattern in codex_prefix_markers:
        if re.search(pattern, lowered, flags=re.I):
            prompt = re.sub(pattern, "", message, count=1, flags=re.I).strip("：:，, \n\t")
            return {"id": path.stem, "type": "codex", "prompt": prompt or message}

    codex_anywhere_markers = [
        r"(让|请|调用|使用|用).{0,24}(vscode|vs\s*code)?.{0,24}codex",
        r"(vscode|vs\s*code).{0,24}codex",
        r"codex.{0,24}(回复|回答|执行|检查|查看|发|发送|告诉我|回给我)",
    ]
    for pattern in codex_anywhere_markers:
        if re.search(pattern, lowered, flags=re.I):
            return {"id": path.stem, "type": "codex", "prompt": message}
    return {"id": path.stem, "type": "openclaw", "message": message}


def main() -> int:
    config = ensure_config()
    paths = shared_dirs(config)
    ensure_shared_layout(paths)
    build_examples(paths)
    state = load_state()
    poll_seconds = int(config["QIAOKELI_REMOTE_AGENT_POLL_SECONDS"])
    heartbeat_seconds = int(config["QIAOKELI_REMOTE_AGENT_HEARTBEAT_SECONDS"])
    last_heartbeat = 0.0

    while True:
        now = time.time()
        if now - last_heartbeat >= heartbeat_seconds:
            write_heartbeat(state, paths)
            save_state(state)
            last_heartbeat = now

        for path, mode in iter_command_files(paths):
            try:
                if now - path.stat().st_mtime < 2:
                    continue
                signature = command_signature(path)
                if state["processed"].get(str(path)) == signature:
                    continue
                command = parse_command_file(path, mode)
                command_id = str(command.get("id") or path.stem)
                started_at = now_iso()
                try:
                    result = process_command(command, config, command_id, mode, paths)
                    response = {
                        "id": command_id,
                        "ok": True,
                        "type": str(command.get("type", "openclaw")),
                        "input_mode": mode,
                        "status": "accepted" if str(command.get("type", "")).strip().lower() in {"codex", "hybrid"} else "completed",
                        "received_at": started_at,
                        "finished_at": now_iso(),
                        "host": socket.gethostname(),
                        "result": result,
                    }
                except Exception as exc:
                    response = {
                        "id": command_id,
                        "ok": False,
                        "type": str(command.get("type", "openclaw")),
                        "input_mode": mode,
                        "received_at": started_at,
                        "finished_at": now_iso(),
                        "host": socket.gethostname(),
                        "error": str(exc),
                    }
                write_response(command_id, response, paths)
                state["processed"][str(path)] = signature
                state["last_command_id"] = command_id
                save_state(state)
                print(f"[remote-agent] processed {path.name} ({mode}) -> {command_id}", flush=True)
            except Exception as exc:
                print(f"[remote-agent] failed to inspect {path}: {exc}", flush=True)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

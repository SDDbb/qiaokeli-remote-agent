#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import secrets
import socket
import sys
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import remote_agent_daemon as daemon


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = daemon.CONFIG_DIR / "nexusdeck_api.token"
API_VERSION = "0.1.0"
DEFAULT_API_CONFIG = {
    "NEXUSDECK_API_BIND_HOST": "127.0.0.1",
    "NEXUSDECK_API_PORT": "8765",
    "NEXUSDECK_API_TOKEN": "",
    "NEXUSDECK_MAX_UPLOAD_BYTES": str(200 * 1024 * 1024),
}

SAFE_ANDROID_ACTIONS = {"status", "current_app", "screenshot", "ui_dump", "open_url"}
HIGH_RISK_ANDROID_ACTIONS = {"shell", "unlock", "tap", "swipe", "input_text", "keyevent", "open_app", "termux_run", "push_file", "pull_file", "playbook"}
SAFE_TYPES = {"status"}
HIGH_RISK_TYPES = {"shell"}
MEDIUM_RISK_TYPES = {"openclaw", "browser", "codex", "cloud_code", "deepseek", "read_file", "android"}
MODES = {"plan", "confirm", "whitelist", "bypass"}
AGENT_PERMISSION_MODES = ("default", "read_only", "workspace_write", "full_access", "bypass")
AGENT_PERMISSION_RANK = {name: index for index, name in enumerate(AGENT_PERMISSION_MODES)}
AGENT_TYPES = {"codex", "cloud_code"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_config() -> dict[str, str]:
    config = daemon.ensure_config()
    values = dict(DEFAULT_API_CONFIG)
    values.update(config)
    return values


def load_or_create_token(config: dict[str, str]) -> str:
    configured = str(config.get("NEXUSDECK_API_TOKEN", "")).strip()
    if configured:
        return configured
    daemon.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token + "\n")
    TOKEN_FILE.chmod(0o600)
    return token


def safe_command_id(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    value = value.strip(".-")
    if value:
        return value[:96]
    return f"nexusdeck-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


def normalize_agent_permission(value: object) -> str:
    raw = str(value or "workspace_write").strip().lower().replace("-", "_")
    aliases = {
        "readonly": "read_only",
        "read_only": "read_only",
        "workspace": "workspace_write",
        "workspace_write": "workspace_write",
        "full": "full_access",
        "full_access": "full_access",
        "fullaccess": "full_access",
        "bypass_permission": "bypass",
        "bypass_permissions": "bypass",
        "bypass": "bypass",
        "default": "default",
    }
    mode = aliases.get(raw, raw)
    if mode not in AGENT_PERMISSION_RANK:
        raise ValueError(f"unsupported agent permission mode: {value}")
    return mode


def max_agent_permission(config: dict[str, str]) -> str:
    return normalize_agent_permission(config.get("QIAOKELI_REMOTE_AGENT_MAX_AGENT_PERMISSION", "workspace_write"))


def permission_allowed(requested: str, maximum: str) -> bool:
    return AGENT_PERMISSION_RANK[requested] <= AGENT_PERMISSION_RANK[maximum]


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def risk_for_command(command_type: str, payload: dict[str, Any]) -> str:
    if command_type in SAFE_TYPES:
        return "safe"
    if command_type in HIGH_RISK_TYPES:
        return "high"
    if command_type == "android":
        action = str(payload.get("action") or "status").strip()
        if action in SAFE_ANDROID_ACTIONS:
            return "safe"
        if action in HIGH_RISK_ANDROID_ACTIONS:
            return "high"
        return "medium"
    if command_type in MEDIUM_RISK_TYPES:
        if command_type in AGENT_TYPES:
            permission_mode = normalize_agent_permission(payload.get("permission_mode"))
            if permission_mode in {"full_access", "bypass"}:
                return "high"
        return "medium"
    return "high"


def allowed_in_whitelist(command_type: str, payload: dict[str, Any]) -> bool:
    if command_type == "status":
        return True
    if command_type != "android":
        return False
    action = str(payload.get("action") or "status").strip()
    if action == "playbook":
        playbook_file = str(payload.get("playbook_file", "")).strip()
        if not playbook_file:
            return False
        try:
            resolved = Path(playbook_file).expanduser().resolve()
            return resolved.is_file() and resolved.is_relative_to((PROJECT_ROOT / "playbooks").resolve())
        except Exception:
            return False
    return action in SAFE_ANDROID_ACTIONS


def build_command(body: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    command_type = str(body.get("type") or "status").strip().lower()
    mode = str(body.get("mode") or "confirm").strip().lower()
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    command_id = safe_command_id(str(body.get("client_request_id") or payload.get("id") or ""))
    command = {"id": command_id, "type": command_type}
    command.update(payload)
    command["id"] = command_id
    command["type"] = command_type
    if command_type in AGENT_TYPES:
        command["permission_mode"] = normalize_agent_permission(command.get("permission_mode"))
    return command_id, mode, payload, command


def command_paths(config: dict[str, str]) -> dict[str, Path]:
    paths = daemon.shared_dirs(config)
    daemon.ensure_shared_layout(paths)
    return paths


def submit_command(config: dict[str, str], command_id: str, command: dict[str, Any]) -> Path:
    paths = command_paths(config)
    target = paths["commands"] / f"{command_id}.json"
    target.write_text(json.dumps(command, ensure_ascii=False, indent=2) + "\n")
    return target


def response_path(config: dict[str, str], command_id: str) -> Path:
    return daemon.shared_dirs(config)["responses"] / f"{safe_command_id(command_id)}.json"


def command_status(config: dict[str, str], command_id: str) -> dict[str, Any]:
    paths = command_paths(config)
    command_id = safe_command_id(command_id)
    response = paths["responses"] / f"{command_id}.json"
    if response.exists():
        data = json.loads(response.read_text(errors="ignore"))
        return {"id": command_id, "status": data.get("status", "completed"), "ok": data.get("ok"), "response": data}
    command_file = paths["commands"] / f"{command_id}.json"
    if command_file.exists():
        return {"id": command_id, "status": "accepted", "ok": None}
    return {"id": command_id, "status": "unknown", "ok": None}


def list_playbooks() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted((PROJECT_ROOT / "playbooks").glob("*.json")):
        target_type = "android" if path.name.startswith("android_") else "browser"
        risk = "safe" if target_type == "android" and "status" in path.name else "medium"
        try:
            raw = json.loads(path.read_text(errors="ignore"))
            steps = raw.get("steps", []) if isinstance(raw, dict) else []
        except Exception:
            steps = []
        items.append(
            {
                "id": path.stem,
                "name": path.stem.replace("_", " "),
                "type": target_type,
                "path": str(path),
                "risk": risk,
                "steps": len(steps) if isinstance(steps, list) else 0,
            }
        )
    return items


def capabilities() -> dict[str, Any]:
    return {
        "version": API_VERSION,
        "modes": ["plan", "confirm", "whitelist", "bypass"],
        "agent_permission_modes": list(AGENT_PERMISSION_MODES),
        "command_types": [
            {"type": "status", "risk": "safe"},
            {"type": "android", "risk": "dynamic"},
            {"type": "browser", "risk": "medium"},
            {"type": "codex", "risk": "medium"},
            {"type": "cloud_code", "risk": "medium"},
            {"type": "deepseek", "risk": "medium"},
            {"type": "openclaw", "risk": "medium"},
            {"type": "shell", "risk": "high"},
            {"type": "read_file", "risk": "medium"},
        ],
        "endpoints": [
            "/api/v1/health",
            "/api/v1/diagnostics",
            "/api/v1/files",
        ],
        "android_actions": [
            {"action": "status", "risk": "safe"},
            {"action": "current_app", "risk": "safe"},
            {"action": "screenshot", "risk": "safe"},
            {"action": "ui_dump", "risk": "safe"},
            {"action": "open_url", "risk": "safe"},
            {"action": "unlock", "risk": "high"},
            {"action": "shell", "risk": "high"},
            {"action": "playbook", "risk": "high"},
        ],
    }


def quick_host_status(config: dict[str, str]) -> dict[str, Any]:
    bind_host = str(config.get("NEXUSDECK_API_BIND_HOST", ""))
    tailscale_ip = bind_host if bind_host.startswith("100.") else ""
    return {
        "host": socket.gethostname(),
        "generated_at": now_iso(),
        "tailscale_ip": tailscale_ip,
        "tailscale_online": bool(tailscale_ip),
        "syncthing_active": daemon.service_active("syncthing.service"),
        "openclaw_gateway_active": daemon.service_active("openclaw-gateway.service"),
        "authorized_research_active": daemon.service_active("qiaokeli-authorized-research.service"),
        "remote_agent_active": daemon.service_active("qiaokeli-remote-agent.service"),
    }


def health(config: dict[str, str]) -> dict[str, Any]:
    host = quick_host_status(config)
    backends = {}
    for name, key in [("codex", "CODEX_BIN"), ("openclaw", "OPENCLAW_BIN"),
                       ("claude", "CLAUDE_BIN"), ("deepseek", "DEEPSEEK_BIN")]:
        bin_path = config.get(key, "")
        backends[name] = {"available": bool(bin_path and Path(bin_path).exists()),
                          "path": bin_path if Path(bin_path).exists() else None}
    return {
        "api": {
            "name": "NexusDeck API",
            "version": API_VERSION,
            "generated_at": now_iso(),
            "host": socket.gethostname(),
            "bind_host": config["NEXUSDECK_API_BIND_HOST"],
            "port": int(config["NEXUSDECK_API_PORT"]),
        },
        "host": host,
        "adb": {"ok": None, "status": "not_checked", "message": "Use diagnostics for ADB status."},
        "capabilities": capabilities(),
        "max_agent_permission": max_agent_permission(config),
        "backends": backends,
    }


def diagnostics(config: dict[str, str]) -> dict[str, Any]:
    summary = health(config)
    summary["host"] = daemon.host_status()
    adb: dict[str, Any]
    try:
        adb = daemon.handle_android({"action": "status", "timeout": 12}, "nexusdeck-health", config)
    except Exception as exc:
        adb = {"ok": False, "error": str(exc)}
    summary["adb"] = adb
    return summary


def artifact_path(artifact_id: str) -> Path:
    decoded = unquote(artifact_id).lstrip("/")
    candidate = (PROJECT_ROOT / decoded).resolve()
    allowed_roots = [
        (PROJECT_ROOT / "runtime").resolve(),
        (PROJECT_ROOT / "playbooks").resolve(),
    ]
    if not any(candidate == root or candidate.is_relative_to(root) for root in allowed_roots):
        raise PermissionError("artifact path is outside allowed roots")
    if not candidate.is_file():
        raise FileNotFoundError(str(candidate))
    return candidate


def upload_target(filename: str) -> Path:
    filename = safe_command_id(filename or "upload.bin")
    target_dir = PROJECT_ROOT / "runtime" / "nexusdeck" / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    if not target.exists():
        return target
    stem = target.stem or "upload"
    suffix = target.suffix
    for index in range(1, 1000):
        candidate = target_dir / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"too many uploads named like {filename}")


def save_upload(data: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    encoded = str(data.get("content_base64") or "")
    if not encoded:
        raise ValueError("missing content_base64")
    max_bytes = int(config.get("NEXUSDECK_MAX_UPLOAD_BYTES") or 200 * 1024 * 1024)
    raw = base64.b64decode(encoded)
    if len(raw) > max_bytes:
        raise ValueError(f"upload too large: {len(raw)} bytes > {max_bytes}")
    target = upload_target(str(data.get("filename") or "upload.bin"))
    target.write_bytes(raw)
    return {"artifact_id": str(target.relative_to(PROJECT_ROOT)), "filename": target.name, "bytes": target.stat().st_size}


def save_upload_stream(handler: BaseHTTPRequestHandler, config: dict[str, str]) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        raise ValueError("missing Content-Length")
    max_bytes = int(config.get("NEXUSDECK_MAX_UPLOAD_BYTES") or 200 * 1024 * 1024)
    if length > max_bytes:
        raise ValueError(f"upload too large: {length} bytes > {max_bytes}")
    filename = unquote(handler.headers.get("X-NexusDeck-Filename", "") or "upload.bin")
    target = upload_target(filename)
    remaining = length
    with target.open("wb") as output:
        while remaining:
            chunk = handler.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                raise IOError("upload stream ended early")
            output.write(chunk)
            remaining -= len(chunk)
    return {"artifact_id": str(target.relative_to(PROJECT_ROOT)), "filename": target.name, "bytes": target.stat().st_size}


class NexusDeckHandler(BaseHTTPRequestHandler):
    server_version = "NexusDeckAPI/0.1"

    def _authorized(self) -> bool:
        expected = getattr(self.server, "api_token")  # type: ignore[attr-defined]
        header = self.headers.get("Authorization", "")
        return bool(expected) and header == f"Bearer {expected}"

    def _config(self) -> dict[str, str]:
        return getattr(self.server, "config")  # type: ignore[attr-defined]

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "missing or invalid bearer token"})
        return False

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        config = self._config()
        try:
            if path == "/api/v1/health":
                json_response(self, HTTPStatus.OK, {"ok": True, "result": health(config)})
                return
            if path == "/api/v1/diagnostics":
                json_response(self, HTTPStatus.OK, {"ok": True, "result": diagnostics(config)})
                return
            if path == "/api/v1/capabilities":
                json_response(self, HTTPStatus.OK, {"ok": True, "result": capabilities()})
                return
            if path == "/api/v1/playbooks":
                json_response(self, HTTPStatus.OK, {"ok": True, "result": list_playbooks()})
                return
            if path.startswith("/api/v1/commands/"):
                command_id = path.rsplit("/", 1)[-1]
                json_response(self, HTTPStatus.OK, {"ok": True, "result": command_status(config, command_id)})
                return
            if path.startswith("/api/v1/responses/"):
                command_id = path.rsplit("/", 1)[-1]
                target = response_path(config, command_id)
                if not target.exists():
                    json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "response not found"})
                    return
                json_response(self, HTTPStatus.OK, {"ok": True, "result": json.loads(target.read_text(errors="ignore"))})
                return
            if path.startswith("/api/v1/files/"):
                artifact_id = path.removeprefix("/api/v1/files/")
                target = artifact_path(artifact_id)
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except Exception as exc:
            json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        config = self._config()
        try:
            if parsed.path == "/api/v1/commands":
                body = read_json(self)
                command_id, mode, payload, command = build_command(body)
                risk = risk_for_command(command["type"], command)
                if command["type"] in AGENT_TYPES:
                    requested_permission = normalize_agent_permission(command.get("permission_mode"))
                    maximum_permission = max_agent_permission(config)
                    if not permission_allowed(requested_permission, maximum_permission):
                        json_response(
                            self,
                            HTTPStatus.FORBIDDEN,
                            {
                                "ok": False,
                                "status": "blocked",
                                "id": command_id,
                                "risk": risk,
                                "error": f"agent permission {requested_permission} exceeds desktop maximum {maximum_permission}",
                            },
                        )
                        return
                confirmed = bool(body.get("confirmed") or payload.get("confirmed"))
                if mode == "plan":
                    json_response(
                        self,
                        HTTPStatus.OK,
                        {"ok": True, "status": "planned", "id": command_id, "risk": risk, "command": command},
                    )
                    return
                if mode == "whitelist" and not allowed_in_whitelist(command["type"], command):
                    json_response(
                        self,
                        HTTPStatus.FORBIDDEN,
                        {"ok": False, "status": "blocked", "id": command_id, "risk": risk, "error": "command is not allowed in whitelist mode"},
                    )
                    return
                if mode == "confirm" and risk == "high" and not confirmed:
                    json_response(
                        self,
                        HTTPStatus.CONFLICT,
                        {"ok": False, "status": "needs_confirmation", "id": command_id, "risk": risk, "command": command},
                    )
                    return
                target = submit_command(config, command_id, command)
                json_response(
                    self,
                    HTTPStatus.ACCEPTED,
                    {"ok": True, "status": "accepted", "id": command_id, "risk": risk, "mode": mode, "command_file": str(target)},
                )
                return
            if parsed.path == "/api/v1/files":
                content_type = self.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    body = read_json(self)
                    result = save_upload(body, config)
                else:
                    result = save_upload_stream(self, config)
                json_response(self, HTTPStatus.CREATED, {"ok": True, "result": result})
                return
            json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except Exception as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NexusDeck HTTP API for qiaokeli remote-agent")
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="", help="Temporary bearer token for this server process.")
    parser.add_argument("--print-token", action="store_true")
    parser.add_argument("--pairing-json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    token = args.token.strip() or load_or_create_token(config)
    host = args.host or config["NEXUSDECK_API_BIND_HOST"]
    port = args.port or int(config["NEXUSDECK_API_PORT"])
    if args.print_token:
        print(token)
        return 0
    if args.pairing_json:
        print(json.dumps({"base_url": f"http://{host}:{port}", "token": token}, ensure_ascii=False, indent=2))
        return 0
    server = ThreadingHTTPServer((host, port), NexusDeckHandler)
    server.config = config  # type: ignore[attr-defined]
    server.api_token = token  # type: ignore[attr-defined]
    print(f"NexusDeck API listening on http://{host}:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

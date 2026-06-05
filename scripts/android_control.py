#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ADB = Path.home() / ".local" / "opt" / "platform-tools" / "adb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "android"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def trim(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "\n...[truncated]..."


class AndroidControl:
    def __init__(self, adb_bin: str, serial: str = "", timeout: int = 30) -> None:
        self.adb_bin = adb_bin
        self.serial = serial
        self.timeout = timeout

    def adb_args(self, *args: str, use_serial: bool = True) -> list[str]:
        command = [self.adb_bin]
        if use_serial and self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        return command

    def run(self, *args: str, timeout: int | None = None, use_serial: bool = True) -> tuple[int, str, str]:
        completed = subprocess.run(
            self.adb_args(*args, use_serial=use_serial),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout or self.timeout,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr

    def run_bytes(self, *args: str, timeout: int | None = None) -> tuple[int, bytes, bytes]:
        completed = subprocess.run(
            self.adb_args(*args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout or self.timeout,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr

    def shell(self, *args: str, timeout: int | None = None) -> tuple[int, str, str]:
        return self.run("shell", *args, timeout=timeout)

    def devices(self) -> dict[str, Any]:
        rc, out, err = self.run("devices", "-l", use_serial=False)
        devices: list[dict[str, str]] = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            item = {"serial": parts[0], "state": parts[1] if len(parts) > 1 else "unknown"}
            for token in parts[2:]:
                if ":" in token:
                    key, value = token.split(":", 1)
                    item[key] = value
            devices.append(item)
        return {"returncode": rc, "stdout": out, "stderr": err, "devices": devices}

    def ensure_serial(self) -> None:
        if self.serial:
            return
        devices = [item for item in self.devices()["devices"] if item.get("state") == "device"]
        if not devices:
            return
        preferred = next((item for item in devices if item.get("usb")), devices[0])
        self.serial = str(preferred["serial"])

    def status(self) -> dict[str, Any]:
        result: dict[str, Any] = {"generated_at": now_iso(), "adb": self.adb_bin, "serial": self.serial, "devices": self.devices()}
        device = next((item for item in result["devices"]["devices"] if item.get("state") == "device"), None)
        if not device:
            return result
        if not self.serial:
            self.serial = str(device["serial"])
            result["serial"] = self.serial
        props = {
            "model": "ro.product.model",
            "device": "ro.product.device",
            "android": "ro.build.version.release",
        }
        for key, prop in props.items():
            rc, out, _err = self.shell("getprop", prop)
            result[key] = out.strip() if rc == 0 else ""
        rc, out, _err = self.shell("wm", "size")
        result["wm_size"] = out.strip() if rc == 0 else ""
        rc, out, _err = self.shell("cmd", "wifi", "status", timeout=15)
        result["wifi_status"] = trim(out.strip()) if rc == 0 else ""
        rc, out, _err = self.shell("dumpsys", "window")
        if rc == 0:
            interesting = []
            for line in out.splitlines():
                if "mCurrentFocus" in line or "mDreamingLockscreen" in line or "mShowingLockscreen" in line:
                    interesting.append(line.strip())
            result["window"] = interesting
        return result

    def current_app(self) -> dict[str, Any]:
        rc, out, err = self.shell("dumpsys", "window")
        lines: list[str] = []
        package = ""
        activity = ""
        if rc == 0:
            for line in out.splitlines():
                stripped = line.strip()
                if "mCurrentFocus" not in stripped and "mFocusedApp" not in stripped:
                    continue
                lines.append(stripped)
                match = re.search(r"\s([A-Za-z0-9_.]+)/(?:([A-Za-z0-9_.$]+)|\.([A-Za-z0-9_.$]+))", stripped)
                if match and not package:
                    package = match.group(1)
                    raw_activity = match.group(2) or f".{match.group(3)}"
                    if raw_activity.startswith("."):
                        raw_activity = f"{package}{raw_activity}"
                    activity = raw_activity.rstrip("}")
        return {
            "returncode": rc,
            "stderr": err.strip(),
            "package": package,
            "activity": activity,
            "window": lines,
        }

    def lockscreen_state(self) -> dict[str, Any]:
        rc, out, err = self.shell("dumpsys", "window")
        lines: list[str] = []
        locked = False
        if rc == 0:
            for line in out.splitlines():
                stripped = line.strip()
                if "mCurrentFocus" in stripped or "mDreamingLockscreen" in stripped or "mShowingLockscreen" in stripped:
                    lines.append(stripped)
                if "mDreamingLockscreen=true" in stripped or "mShowingLockscreen=true" in stripped:
                    locked = True
                if "NotificationShade" in stripped and ("mCurrentFocus" in stripped or "mFocusedApp" in stripped):
                    locked = True
        return {"returncode": rc, "stderr": err.strip(), "locked": locked, "window": lines}

    def display_state(self) -> dict[str, Any]:
        rc, out, err = self.shell("dumpsys", "display")
        display_state = ""
        policy = ""
        if rc == 0:
            state_match = re.search(r"Display State=([A-Z_]+)", out)
            policy_match = re.search(r"mDisplayPolicy=([A-Z_]+)", out)
            display_state = state_match.group(1) if state_match else ""
            policy = policy_match.group(1) if policy_match else ""
        rc2, out2, err2 = self.shell("dumpsys", "power")
        wakefulness = ""
        if rc2 == 0:
            wake_match = re.search(r"mWakefulness=([A-Za-z_]+)", out2)
            wakefulness = wake_match.group(1) if wake_match else ""
        return {
            "returncode": rc if rc != 0 else rc2,
            "stderr": (err.strip() or err2.strip()),
            "display_state": display_state,
            "display_policy": policy,
            "wakefulness": wakefulness,
            "screen_on": display_state == "ON" and wakefulness == "Awake",
        }

    def deviceidle_disabled(self) -> bool:
        rc, out, _err = self.shell("dumpsys", "deviceidle", timeout=15)
        return rc == 0 and ("Deep idle mode disabled" in out or "Light idle mode disabled" in out)

    def wake_screen(self) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        disabled_deviceidle = False

        def keyevent(key: str) -> None:
            rc, out, err = self.shell("input", "keyevent", key)
            steps.append({"action": "keyevent", "key": key, "returncode": rc, "stdout": out.strip(), "stderr": err.strip()})

        before = self.display_state()
        steps.append({"action": "display_before", "state": before})
        if before["screen_on"]:
            return {"screen_on": True, "disabled_deviceidle": False, "steps": steps}

        keyevent("KEYCODE_WAKEUP")
        time.sleep(0.8)
        after_wake = self.display_state()
        steps.append({"action": "display_after_wakeup", "state": after_wake})
        if after_wake["screen_on"]:
            return {"screen_on": True, "disabled_deviceidle": False, "steps": steps}

        if not self.deviceidle_disabled():
            rc, out, err = self.shell("cmd", "deviceidle", "disable", timeout=15)
            disabled_deviceidle = rc == 0
            steps.append({"action": "deviceidle_disable", "returncode": rc, "stdout": out.strip(), "stderr": err.strip()})
            time.sleep(0.3)

        for key in ("KEYCODE_WAKEUP", "KEYCODE_MENU"):
            keyevent(key)
            time.sleep(0.6)
            state = self.display_state()
            steps.append({"action": f"display_after_{key.lower()}", "state": state})
            if state["screen_on"]:
                return {"screen_on": True, "disabled_deviceidle": disabled_deviceidle, "steps": steps}

        return {"screen_on": False, "disabled_deviceidle": disabled_deviceidle, "steps": steps}

    def restore_deviceidle(self) -> dict[str, Any]:
        rc, out, err = self.shell("cmd", "deviceidle", "enable", timeout=15)
        return {"action": "deviceidle_enable", "returncode": rc, "stdout": out.strip(), "stderr": err.strip()}

    def enter_pin(self, pin: str) -> dict[str, Any]:
        if pin.isdigit():
            keys = [f"KEYCODE_{digit}" for digit in pin] + ["KEYCODE_ENTER"]
            rc, out, err = self.shell("input", "keyevent", *keys)
            return {"method": "keyevent_digits", "returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "digits": len(pin)}

        typed = self.input_text(pin)
        rc, out, err = self.shell("input", "keyevent", "KEYCODE_ENTER")
        return {
            "method": "text",
            "input_text": typed,
            "enter": {"returncode": rc, "stdout": out.strip(), "stderr": err.strip()},
            "digits": len(pin),
        }

    def tcpip(self, port: int) -> dict[str, Any]:
        rc, out, err = self.run("tcpip", str(port), use_serial=bool(self.serial))
        return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "port": port}

    def connect(self, target: str) -> dict[str, Any]:
        rc, out, err = self.run("connect", target, use_serial=False)
        return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "target": target}

    def screenshot(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / f"android-screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        rc, out, err = self.run_bytes("exec-out", "screencap", "-p", timeout=60)
        if rc == 0:
            target.write_bytes(out)
        return {"returncode": rc, "stderr": err.decode(errors="ignore").strip(), "path": str(target), "bytes": len(out)}

    def ui_dump(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        remote = "/sdcard/window.xml"
        target = output_dir / f"android-window-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xml"
        rc, out, err = self.shell("uiautomator", "dump", remote, timeout=60)
        if rc != 0:
            return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "path": str(target)}
        rc2, out2, err2 = self.run("pull", remote, str(target), timeout=60)
        return {"returncode": rc2, "stdout": out2.strip(), "stderr": err2.strip(), "path": str(target), "bytes": target.stat().st_size if target.exists() else 0}

    def input_text(self, text: str) -> dict[str, Any]:
        encoded = text.replace("%", "%25").replace(" ", "%s")
        rc, out, err = self.shell("input", "text", encoded)
        return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip()}

    def open_app(self, package: str, activity: str = "") -> dict[str, Any]:
        if activity:
            rc, out, err = self.shell("am", "start", "-n", f"{package}/{activity}")
        else:
            rc, out, err = self.shell("monkey", "-p", package, "1")
        return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "package": package, "activity": activity}

    def open_url(self, url: str) -> dict[str, Any]:
        if not url:
            raise ValueError("missing URL")
        rc, out, err = self.shell("am", "start", "-a", "android.intent.action.VIEW", "-d", url)
        return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "url": url}

    def push_file(self, local_path: str, remote_path: str) -> dict[str, Any]:
        if not local_path or not remote_path:
            raise ValueError("push_file requires --local-path and --remote-path")
        source = Path(local_path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(str(source))
        rc, out, err = self.run("push", str(source), remote_path, timeout=120)
        return {
            "returncode": rc,
            "stdout": out.strip(),
            "stderr": err.strip(),
            "local_path": str(source),
            "remote_path": remote_path,
            "bytes": source.stat().st_size,
        }

    def pull_file(self, remote_path: str, local_path: str, output_dir: Path) -> dict[str, Any]:
        if not remote_path:
            raise ValueError("pull_file requires --remote-path")
        if local_path:
            target = Path(local_path).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            target = output_dir / Path(remote_path).name
        rc, out, err = self.run("pull", remote_path, str(target), timeout=120)
        return {
            "returncode": rc,
            "stdout": out.strip(),
            "stderr": err.strip(),
            "remote_path": remote_path,
            "local_path": str(target),
            "bytes": target.stat().st_size if target.exists() else 0,
        }

    def termux_run(self, command: str) -> dict[str, Any]:
        opened = self.open_app("com.termux")
        time.sleep(1)
        typed = self.input_text(command)
        rc, out, err = self.shell("input", "keyevent", "ENTER")
        return {"open_app": opened, "input_text": typed, "enter": {"returncode": rc, "stdout": out.strip(), "stderr": err.strip()}}

    def unlock(self, pin: str, swipe: tuple[int, int, int, int, int]) -> dict[str, Any]:
        if not pin:
            raise ValueError("missing unlock PIN; set ANDROID_UNLOCK_PIN for this process")
        steps: list[dict[str, Any]] = []
        wake = self.wake_screen()
        steps.extend(wake["steps"])
        if not wake["screen_on"]:
            if wake["disabled_deviceidle"]:
                steps.append(self.restore_deviceidle())
            return {"status": "screen_not_awake", "steps": steps}

        before = self.lockscreen_state()
        if not before["locked"]:
            if wake["disabled_deviceidle"]:
                steps.append(self.restore_deviceidle())
            return {"status": "already_unlocked", "before": before, "steps": steps}

        rc, out, err = self.shell("cmd", "statusbar", "collapse")
        steps.append({"action": "statusbar_collapse", "returncode": rc, "stdout": out.strip(), "stderr": err.strip()})
        time.sleep(0.2)

        swipes = [swipe]
        fallback_swipe = (540, 2230, 540, 1450, 700)
        if swipe != fallback_swipe:
            swipes.append(fallback_swipe)
        for index, item in enumerate(swipes):
            x1, y1, x2, y2, duration = item
            rc, out, err = self.shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))
            steps.append({"action": "swipe", "attempt": index + 1, "returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "swipe": item})
            time.sleep(0.8)
            steps.append({"action": "pin_entry", "attempt": index + 1, "result": self.enter_pin(pin)})
            time.sleep(1.2)
            after_attempt = self.lockscreen_state()
            steps.append({"action": "lockscreen_after_attempt", "attempt": index + 1, "state": after_attempt})
            if not after_attempt["locked"]:
                if wake["disabled_deviceidle"]:
                    steps.append(self.restore_deviceidle())
                return {"status": "unlocked", "before": before, "after": after_attempt, "steps": steps}

        if wake["disabled_deviceidle"]:
            steps.append(self.restore_deviceidle())
        after = self.lockscreen_state()
        return {"status": "still_locked", "before": before, "after": after, "steps": steps}

    def run_action(self, action: str, args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
        if action == "status":
            return self.status()
        if action == "tcpip":
            return self.tcpip(args.port)
        if action == "connect":
            return self.connect(args.target)
        if action == "screenshot":
            return self.screenshot(output_dir)
        if action == "ui_dump":
            return self.ui_dump(output_dir)
        if action == "current_app":
            return self.current_app()
        if action == "tap":
            rc, out, err = self.shell("input", "tap", str(args.x), str(args.y))
            return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "x": args.x, "y": args.y}
        if action == "swipe":
            rc, out, err = self.shell("input", "swipe", str(args.x1), str(args.y1), str(args.x2), str(args.y2), str(args.duration_ms))
            return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip()}
        if action == "input_text":
            return self.input_text(args.text)
        if action == "keyevent":
            rc, out, err = self.shell("input", "keyevent", args.key)
            return {"returncode": rc, "stdout": out.strip(), "stderr": err.strip(), "key": args.key}
        if action == "open_app":
            return self.open_app(args.package, args.activity)
        if action == "open_url":
            return self.open_url(args.url)
        if action == "push_file":
            return self.push_file(args.local_path, args.remote_path)
        if action == "pull_file":
            return self.pull_file(args.remote_path, args.local_path, output_dir)
        if action == "shell":
            rc, out, err = self.shell(*args.shell_args, timeout=args.timeout)
            return {"returncode": rc, "stdout": trim(out), "stderr": trim(err)}
        if action == "termux_run":
            return self.termux_run(args.text)
        if action == "unlock":
            pin = os.environ.get("ANDROID_UNLOCK_PIN", "")
            swipe = (args.x1, args.y1, args.x2, args.y2, args.duration_ms)
            return self.unlock(pin, swipe)
        raise ValueError(f"unsupported android action: {action}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Control an Android device through adb")
    parser.add_argument("action", nargs="?", default="status", choices=["status", "tcpip", "connect", "screenshot", "ui_dump", "current_app", "tap", "swipe", "input_text", "keyevent", "open_app", "open_url", "push_file", "pull_file", "shell", "termux_run", "unlock", "playbook"])
    parser.add_argument("--adb-bin", default=os.environ.get("ANDROID_ADB_BIN") or (str(DEFAULT_ADB) if DEFAULT_ADB.exists() else "adb"))
    parser.add_argument("--serial", default=os.environ.get("ANDROID_ADB_SERIAL", ""))
    parser.add_argument("--target", default=os.environ.get("ANDROID_ADB_TARGET", ""))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--x1", type=int, default=540)
    parser.add_argument("--y1", type=int, default=1900)
    parser.add_argument("--x2", type=int, default=540)
    parser.add_argument("--y2", type=int, default=600)
    parser.add_argument("--duration-ms", type=int, default=300)
    parser.add_argument("--text", default="")
    parser.add_argument("--key", default="KEYCODE_WAKEUP")
    parser.add_argument("--package", default="")
    parser.add_argument("--activity", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--local-path", default="")
    parser.add_argument("--remote-path", default="")
    parser.add_argument("--shell-args", nargs=argparse.REMAINDER, default=[])
    parser.add_argument("--playbook-file", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    control = AndroidControl(args.adb_bin, serial=args.serial, timeout=args.timeout)
    started = now_iso()
    try:
        if args.action == "playbook":
            control.ensure_serial()
            if not args.playbook_file:
                raise ValueError("missing --playbook-file")
            playbook = json.loads(Path(args.playbook_file).expanduser().read_text())
            steps = playbook.get("steps", [])
            results = []
            for index, step in enumerate(steps):
                step_args = argparse.Namespace(**vars(args))
                for key, value in step.items():
                    setattr(step_args, key.replace("-", "_"), value)
                step_action = str(step.get("action", "")).strip()
                results.append({"index": index, "action": step_action, "result": control.run_action(step_action, step_args, output_dir)})
            payload = {"ok": True, "started_at": started, "finished_at": now_iso(), "action": "playbook", "results": results}
        else:
            if args.action != "connect":
                control.ensure_serial()
            result = control.run_action(args.action, args, output_dir)
            payload = {"ok": True, "started_at": started, "finished_at": now_iso(), "action": args.action, "result": result}
    except Exception as exc:
        payload = {"ok": False, "started_at": started, "finished_at": now_iso(), "action": args.action, "error": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

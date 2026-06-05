# Qiaokeli Remote Agent

> **2026-05-31 archive notice — hybrid / tokensave 流水线已下线**
>
> 旧入口 `hybrid_local_run.py`、`tokensave_local.sh` / `tokensave_doc_local.sh` /
> `tokensave_patch_local.sh` 已归档到
> [`~/桌面/00-archive/02-agent-tools/remote-agent/scripts/`](../../00-archive/02-agent-tools/remote-agent/scripts/)，
> 对应的 `~/.local/bin/qiaokeli-hybrid-run` / `qiaokeli-tokensave` 已移除。
>
> 取代物：`~/.local/bin/qiaokeli-cheap`（独立单文件 Python CLI，DeepSeek-Flash
> 直连）。原所在的 openclaw-host 项目 2026-05-31 整体归档到
> [`~/桌面/00-archive/03-infra/openclaw-host/`](../../00-archive/03-infra/openclaw-host/)。
>
> 注：库文件 `scripts/remote_agent_hybrid_job.py` 仍被 `remote_agent_daemon.py`
> import，未一并归档；daemon 可按需由 systemd 用户服务启动。

A simple personal remote agent built on:
- Syncthing for file transport
- Tailscale for private network reachability
- OpenClaw for natural-language task execution

It is intentionally mailbox-shaped:
- phone writes commands into a shared folder
- Fedora daemon picks them up
- results come back as JSON
- status heartbeat stays in the same shared folder

> Historical note: this repo used to reference a standalone OpenClaw host
> infrastructure project at `~/桌面/03-infra/openclaw-host` for supervisor
> policy and host actions. That project was archived 2026-05-31 (see
> `~/桌面/00-archive/03-infra/openclaw-host/`). The OpenClaw npm CLI itself
> is still available on-host and used by this daemon for `openclaw` tasks.

## Modes

Structured commands:
- drop JSON files into `commands/`

Natural-language commands:
- drop plain text files into `inbox/`
- the daemon treats them as `openclaw` tasks automatically
- if the text clearly asks for `codex`, it routes to local `codex exec`
- the legacy `百炼/Bailian` + `Codex` hybrid routing was archived 2026-05-31
  alongside the openclaw-host project; the supported command types listed
  below no longer include `hybrid`

## Shared folder

Default shared root:

```text
~/Sync/30_Projects/remote_agent
```

Layout:
- `commands/`: JSON commands
- `inbox/`: natural-language `.txt` or `.md` files
- `responses/`: command results
- `status/heartbeat.json`: current host status
- `examples/`: starter examples

## Supported command types

- `status`
- `openclaw`
- `browser`
- `codex`
- `android`
- `shell`
- `read_file`

## Quick start

Install or update the service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now qiaokeli-remote-agent.service
```

Local test:

```bash
python3 scripts/remote_agent_submit.py --type status
python3 scripts/remote_agent_status.py
python3 scripts/remote_agent_submit.py --type browser
python3 scripts/remote_agent_submit.py --type android --android-action status
```

## NexusDeck mobile console

NexusDeck is the Android control console for this project. It uses a dedicated
HTTP API over Tailscale, while the desktop side keeps using the existing
mailbox daemon and Android ADB control layer.

Start or inspect the desktop API:

```bash
python3 scripts/remote_agent_api.py --pairing-json
python3 scripts/remote_agent_api.py --host 127.0.0.1 --port 8765
systemctl --user enable --now qiaokeli-nexusdeck-api.service
```

The API requires `Authorization: Bearer <token>` for every request. If
`NEXUSDECK_API_TOKEN` is empty, the API creates a local token file under
`~/.config/qiaokeli-remote-agent/nexusdeck_api.token`. To reach the API from
the phone, set `NEXUSDECK_API_BIND_HOST` to the Fedora host's Tailscale IP in
`~/.config/qiaokeli-remote-agent/config.env`, then restart the service.

Open the Android project in Android Studio:

```text
nexusdeck-android/
```

Or build the debug APK from the command line:

```bash
bash scripts/setup_nexusdeck_android_build_env.sh
bash nexusdeck-android/build-apk.sh
~/.local/opt/platform-tools/adb install -r nexusdeck-android/app/build/outputs/apk/debug/app-debug.apk
```

The setup script installs Android command-line tools, Android SDK packages, and
Gradle under `~/.local/opt/`. Downloads are resumable through
`~/.cache/nexusdeck-build/`, so a slow network can continue later.

In the NexusDeck app, fill the API base URL and token on the Settings tab. The
first app version includes Deck, Agent, Phone, Files, and Settings tabs, with
work modes `plan`, `confirm`, `whitelist`, and `bypass`.

NexusDeck API endpoints:

- `GET /api/v1/health`
- `GET /api/v1/diagnostics`
- `GET /api/v1/capabilities`
- `GET /api/v1/playbooks`
- `POST /api/v1/commands`
- `GET /api/v1/commands/<id>`
- `GET /api/v1/responses/<id>`
- `GET /api/v1/files/<artifact_id>`
- `POST /api/v1/files`

`/api/v1/health` is intentionally lightweight and does not block on ADB.
Use `/api/v1/diagnostics` when the phone UI needs the deeper ADB status check.

Agent backends that can execute code (`codex`, `hybrid`, `cloud_code`) accept
`permission_mode`: `default`, `read_only`, `workspace_write`, `full_access`,
or `bypass`. The desktop still enforces
`QIAOKELI_REMOTE_AGENT_MAX_AGENT_PERMISSION` as the upper bound.

## Natural-language use

Create a text file under:

```text
~/Sync/30_Projects/remote_agent/inbox/
```

Example:

```text
巧克力，读取当前主机状态，并告诉我 Syncthing 和 OpenClaw 是否正常。
```

The daemon will write the answer into:

```text
~/Sync/30_Projects/remote_agent/responses/<same-stem>.json
```

Codex example:

```text
让 Codex 检查当前仓库 README 有没有明显问题，并直接告诉我结论。
```

This does not click the VS Code extension UI directly. It calls the local
`codex` CLI on the Fedora host and returns the result through the mailbox.
The first response may show `status: accepted`; the same response file is then
overwritten with the final `completed` result after Codex finishes.

## Android device control

Use `android` when the desktop agent should inspect or control an Android phone
through ADB. USB ADB is the bootstrap path; wireless ADB over the LAN or
Tailscale is the intended daily path once authorized.

The planned phone-side control app is named **NexusDeck**. Its job is to unify
Android/Fedora remote-agent status checks, command submission, screenshots,
file transfer, and playbook entry points behind one mobile console.

Direct local checks:

```bash
python3 scripts/android_control.py status
python3 scripts/android_control.py screenshot
python3 scripts/android_control.py ui_dump
python3 scripts/android_control.py current_app
python3 scripts/android_control.py tap --x 540 --y 1800
python3 scripts/android_control.py open_url --url https://example.com
python3 scripts/android_control.py open_app --package com.termux
python3 scripts/android_control.py push_file --local-path ./README.md --remote-path /sdcard/Download/README.md
python3 scripts/android_control.py pull_file --remote-path /sdcard/Download/README.md
ANDROID_UNLOCK_PIN=**** python3 scripts/android_control.py unlock
```

Submit through the mailbox:

```bash
python3 scripts/remote_agent_submit.py --type android --android-action status
python3 scripts/remote_agent_submit.py --type android --android-action screenshot
python3 scripts/remote_agent_submit.py --type android --android-action keyevent --key KEYCODE_WAKEUP
python3 scripts/remote_agent_submit.py --type android --android-action open_url --url https://example.com
python3 scripts/remote_agent_submit.py --type android --android-action playbook --playbook-file ./playbooks/android_link_and_status.json
```

Wireless ADB bootstrap while USB is still attached:

```bash
adb tcpip 5555
adb connect <phone-lan-or-tailscale-ip>:5555
```

The Android control layer is meant to give desktop Codex/Claude/OpenClaw a
phone tool surface: screenshots, UI hierarchy, taps, text input, app launch,
key events, shell probes, URL opening, file push/pull, unlock for owned
devices, and Termux command entry.
Do not store the unlock PIN in repo files or shared config; pass it only as a
short-lived process environment variable when needed.

## Browser playbooks

Use `browser` for deterministic web work that would otherwise be slow or flaky
through a general-purpose chat agent:

- logged-in forms
- issue trackers
- repeatable posting/comment flows
- page checks that need real browser state but not open-ended reasoning

Submit a structured playbook:

```bash
python3 scripts/remote_agent_submit.py \
  --type browser \
  --playbook-file ./playbooks/example.com.json
```

Minimal playbook example:

```json
{
  "steps": [
    {"action": "open", "url": "https://example.com"},
    {"action": "wait", "text": "Example Domain", "timeout_ms": 10000},
    {"action": "evaluate", "fn": "() => ({title: document.title, href: location.href})"}
  ]
}
```

Supported actions in the built-in runner:

- `status`
- `tabs`
- `pick_tab`
- `focus`
- `open`
- `navigate`
- `wait`
- `snapshot`
- `evaluate`
- `click`
- `press`
- `type`
- `fill`

`pick_tab` is useful when the OpenClaw browser is already logged into a site and
you want to reuse that session without guessing a CDP target id.

## Performance notes

The fastest path depends on the task shape:

- use `openclaw` for open-ended natural-language tasks
- use `browser` for deterministic browser steps

For browser-heavy work, a few rules help a lot:

- prefer `evaluate` with stable DOM selectors for dynamic forms
- use `snapshot --efficient --interactive` only when you actually need refs
- avoid parallel focus/snapshot operations against the same browser profile
- keep the dedicated OpenClaw browser profile logged into your target sites
- prefer a playbook over a general agent prompt when the workflow is repeatable

## Desktop use for cheap drafts

For bounded draft work (doc skeletons, code snippets, classification,
summaries), use the standalone `qiaokeli-cheap` CLI installed at
`~/.local/bin/qiaokeli-cheap` (direct DeepSeek-Flash, no gateway). The legacy
`tokensave_*` hybrid pipeline was archived 2026-05-31; see the archive notice
at the top of this README for details.

## OpenHands Interactive Tunnel for Remote Vibe Coding

The tunnel server enables **real-time interactive OpenHands CLI access from Android phones**
via Tailscale private network. Perfect for remote vibe coding on the go.

Features:
- Persistent OpenHands process on your desktop - reconnect anywhere without losing your session
- WebSocket endpoint - works with any WebSocket client on Android (Termux recommended)
- Full ANSI color support - preserves the native OpenHands CLI look and feel
- Authentication support for extra security
- Automatic reconnection - the server keeps your OpenHands session when you drop connection

Quick start server:
```bash
# Install the service (user-level, no root needed)
cp ~/桌面/02-agent-tools/remote-agent/systemd/qiaokeli-openhands-tunnel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now qiaokeli-openhands-tunnel.service
journalctl --user -u qiaokeli-openhands-tunnel.service -f
```

Connect from Android Termux:
```bash
# Install dependencies
pkg install python
pip install websockets

# Run the simple client
python ~/path/to/qiaokeli-remote-agent/scripts/simple_terminal_client.py ws://<tailscale-ip>:8765 [auth-token]
```

The client preserves all ANSI colors and interactivity just like the native desktop CLI.

Connection URL is printed to the journal when the server starts. If you use Tailscale (recommended),
the URL is something like `ws://100.xxx.xxx.xxx:8765`.

Configuration is at `~/.config/qiaokeli-remote-agent/tunnel_config.env`.

## Notes

- `openclaw` tasks default to the `resident` agent
- `browser` tasks use the dedicated OpenClaw browser profile directly
- `codex` tasks default to the local Codex CLI workdir configured in `config.env`
- natural-language tasks are asynchronous, not live RPC
- this is optimized for reliability and simple cross-device use
- the OpenHands tunnel is for live interactive remote vibe coding from phone

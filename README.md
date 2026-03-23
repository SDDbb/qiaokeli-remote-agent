# Qiaokeli Remote Agent

A simple personal remote agent built on:
- Syncthing for file transport
- Tailscale for private network reachability
- OpenClaw for natural-language task execution

It is intentionally mailbox-shaped:
- phone writes commands into a shared folder
- Fedora daemon picks them up
- results come back as JSON
- status heartbeat stays in the same shared folder

## Modes

Structured commands:
- drop JSON files into `commands/`

Natural-language commands:
- drop plain text files into `inbox/`
- the daemon treats them as `openclaw` tasks automatically
- if the text clearly asks for `codex`, it routes to local `codex exec`
- if the text asks for `百炼/Bailian` and `Codex` together, it routes to the hybrid pipeline

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
- `codex`
- `hybrid`
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
```

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

Hybrid example:

```text
先让百炼执行，再让 Codex 审阅：检查当前仓库 README 有没有明显问题，并直接告诉我最终结论。
```

This routes to the Bailian-backed OpenClaw worker first, then sends the worker
draft to the local `codex` CLI for final review.

## Desktop use with Codex

If you are working directly on the Fedora desktop, use:

```bash
qiaokeli-hybrid-run "先让百炼执行，再让 Codex 审阅：检查当前仓库 README 有没有明显问题，并给出最终结论。"
```

This is the intended path when you are chatting with Codex in VS Code and want
Codex to dispatch low-cost execution work to Bailian in the background.

Keyword convention for this repo:

- if you tell Codex `tokensave`, it should prefer this hybrid pipeline
- local helper: `qiaokeli-tokensave "你的任务"`
- repo script helper: `scripts/tokensave_local.sh "你的任务"`
- when `tokensave` is present, the default is now full execution flow rather than plan-only fallback
- if the pipeline cannot safely continue, it should report the blocker explicitly instead of silently bypassing tokensave

When `tokensave` is used, the backend now asks Bailian/OpenClaw to classify the
task before drafting. The current internal modes are:

- `brief`: project brief, social post, progress summary, README-style update
- `patch`: bug fix, code change, test/update plan, implementation draft
- `research`: multi-file reading, investigation, strategy note, comparison
- `general`: fallback if the task does not fit clearly

You do not need to write these modes explicitly. The classifier chooses one in
the background and includes it in the JSON metadata.

The worker backend is also chosen automatically:

- `direct_bailian`: pure text drafting, summarization, planning
- `openclaw_bailian`: tasks that likely need OpenClaw context, agent memory, browser/tool coupling, or local project grounding

The frontend command is still just `tokensave`.

Codex review depth is also chosen automatically:

- `light`: low-risk brief/general drafting, minimal consistency review
- `standard`: normal research/synthesis review
- `strict`: patch/code/system-sensitive tasks

For engineering work, `tokensave` now also emits structured planning fields:

- `engineering_context`: `new_project | bugfix | maintenance | none`
- `execution_intent`: `plan_only | apply_patch | tool_exec`
- `files_to_check`
- `proposed_changes`
- `verification_steps`

This is intended to make `tokensave` useful for:

- new project scaffolding
- bug triage and root-cause planning
- maintenance/refactor planning

while keeping the frontend command unchanged.

Execution layer status:

- `plan_only`: no automatic write, returns planning output only
- `apply_patch`: after Codex review, the local Codex CLI can be invoked again to apply approved changes and report execution results
- `tool_exec`: still blocked by default in the current implementation

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
cp ~/桌面/qiaokeli-remote-agent/systemd/qiaokeli-openhands-tunnel.service ~/.config/systemd/user/
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
- `codex` tasks default to the local Codex CLI workdir configured in `config.env`
- `hybrid` tasks use Bailian via OpenClaw for the execution draft, then Codex for the final review
- natural-language tasks are asynchronous, not live RPC
- this is optimized for reliability and simple cross-device use
- the OpenHands tunnel is for live interactive remote vibe coding from phone

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

## Notes

- `openclaw` tasks default to the `resident` agent
- `codex` tasks default to the local Codex CLI workdir configured in `config.env`
- `hybrid` tasks use Bailian via OpenClaw for the execution draft, then Codex for the final review
- natural-language tasks are asynchronous, not live RPC
- this is optimized for reliability and simple cross-device use

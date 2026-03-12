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

## Notes

- `openclaw` tasks default to the `resident` agent
- natural-language tasks are asynchronous, not live RPC
- this is optimized for reliability and simple cross-device use

# Tokensave Work Order

Date: 2026-03-15

## Goal

Build a low-cost execution path where:

- Bailian/OpenClaw handles the cheap execution draft
- Codex handles the final review and sign-off
- the user can trigger the path with the keyword `tokensave`
- the desktop flow is the primary entrypoint, not the phone mailbox

## Delivered

### 1. Hybrid pipeline

Added a new hybrid execution path:

- worker: Bailian via OpenClaw
- reviewer: local Codex CLI
- output: final reviewed reply only

Key files:

- `scripts/remote_agent_hybrid_job.py`
- `scripts/hybrid_local_run.py`
- `scripts/remote_agent_daemon.py`

### 2. Desktop-first command

Added a local command for desktop use:

```bash
qiaokeli-hybrid-run "先让百炼执行，再让 Codex 审阅：你的任务"
```

This is the intended path when talking to Codex on the Fedora desktop.

### 3. `tokensave` convention

Added a repo-level rule in the main project:

- if the user includes `tokensave`, prefer the hybrid pipeline

Key file:

- `/home/zhujintao/桌面/数据筛选LLM/AGENTS.md`

Added a local helper:

```bash
qiaokeli-tokensave "tokensave 你的任务"
```

This strips the keyword and forwards the task into the hybrid pipeline.

### 4. Mailbox support

The mailbox agent still works, but it is now secondary.

Natural-language hybrid examples:

```text
先让百炼执行，再让 Codex 审阅：检查当前仓库 README 有没有明显问题，并直接告诉我最终结论。
```

## Verification

The following checks were run successfully:

```bash
qiaokeli-hybrid-run "先让百炼执行，再让 Codex 审阅：只回复一行 hybrid-ok，不要额外内容。"
qiaokeli-tokensave "tokensave 只回复一行 tokensave-ok，不要额外内容。"
python3 -m py_compile scripts/remote_agent_daemon.py scripts/remote_agent_hybrid_job.py scripts/hybrid_local_run.py scripts/remote_agent_submit.py
systemctl --user restart qiaokeli-remote-agent.service
```

Observed outputs:

- `hybrid-ok`
- `tokensave-ok`

## Current usage

### Default recommendation

When working locally with Codex in VS Code, phrase tasks like:

```text
tokensave 帮我检查当前仓库 README 有没有明显问题，并给出最终结论。
```

### Direct shell usage

```bash
qiaokeli-tokensave "tokensave 帮我检查当前仓库 README 有没有明显问题，并给出最终结论。"
```

## Limits

- This path currently returns reviewed text, not applied patches.
- Bailian does not directly write to the main working tree.
- Code-changing tasks should still add local verification before any final write step.

## Next step

Recommended next upgrade:

- extend `tokensave` from text-only review to:
  - draft patch
  - run tests
  - produce final Codex verdict
  - optionally apply changes only after explicit approval

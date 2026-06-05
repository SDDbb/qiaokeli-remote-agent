# OpenHands Local Launchers (实验)

便宜的 OpenHands CLI 启动器，配合本机已经接好的两个 coding endpoint。

## 来源

从 `02-agent-tools/openhands-playground/local/` 迁来。openhands-playground 项目本身已归档到 `00-archive/02-agent-tools/openhands-playground/`（归档日期 2026-05-28），原因是它本质是 remote-agent 的陈旧 fork，共享同一份 systemd 服务和 `~/.config` 配置目录，无法独立运行。这三个文件是其中唯一的独有产物，迁回主线作为实验组件保留。

## 文件

- `run-bailian.sh` — 从 `~/.openclaw/.env` 读 `CODING_PLAN_API_KEY`，启动 OpenHands 跑百炼 `qwen3-coder-plus`
- `run-ark.sh` — 从 `~/桌面/api.txt` 第一行读 Ark API key，启动 OpenHands 跑火山 `ark-code-latest`
- `bin/git` — `LD_LIBRARY_PATH` 清理包装，避免 OpenHands 进程内 git 报库冲突

## 用法

```bash
./run-bailian.sh                                    # 用当前目录作 workspace
./run-bailian.sh ~/桌面/05-upstream/openhands-workspace
./run-ark.sh ~/桌面/05-upstream/openhands-workspace
```

## 状态

实验性。OpenHands CLI 本身在 `~/.local/bin/openhands`；上游参考仓库在 `~/桌面/05-upstream/openhands-upstream`。

如果想做成 PATH 上可直接调用的 `openhands-bailian` / `openhands-ark` 命令，参考归档项目里 `local/README-local.md` 的旧用法（之前是通过 alias 或 symlink 到 `~/.local/bin`）。
